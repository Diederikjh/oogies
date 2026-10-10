#include "HCNetSDK.h"
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>

static std::atomic<unsigned long long> stream_bytes{0};
static std::atomic<unsigned long long> stream_chunks{0};
static std::mutex stream_mutex;
static std::ofstream stream_file;
static bool sdk_logging_enabled = false;

static bool initialize_sdk() {
    NET_DVR_LOCAL_SDK_PATH sdk_path{};
    std::strncpy(sdk_path.sPath, "/sdk/lib", sizeof(sdk_path.sPath) - 1);
    NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, &sdk_path);
    char crypto_path[] = "/sdk/lib/libcrypto.so.1.1";
    char tls_path[] = "/sdk/lib/libssl.so.1.1";
    if (!NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_LIBEAY_PATH, crypto_path) ||
        !NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SSLEAY_PATH, tls_path)) {
        std::cout << "CAM_SDK_REPORT {\"config_error\":" << NET_DVR_GetLastError()
                  << ",\"login_calls\":0}" << std::endl;
        return false;
    }
    if (NET_DVR_Init()) {
        const char *log_path = std::getenv("CAM_SDK_LOG_DIR");
        if (log_path && *log_path) {
            sdk_logging_enabled = NET_DVR_SetLogToFile(3, const_cast<char *>(log_path), TRUE);
            if (!sdk_logging_enabled) {
                const DWORD error = NET_DVR_GetLastError();
                NET_DVR_Cleanup();
                std::cout << "CAM_SDK_REPORT {\"logging_error\":" << error
                          << ",\"login_calls\":0}" << std::endl;
                return false;
            }
        }
        return true;
    }
    std::cout << "CAM_SDK_REPORT {\"init_error\":" << NET_DVR_GetLastError()
              << ",\"login_calls\":0}" << std::endl;
    return false;
}

static void CALLBACK on_stream(LONG, DWORD type, BYTE *data, DWORD length, void *) {
    if (type != NET_DVR_SYSHEAD && type != NET_DVR_STREAMDATA) return;
    std::lock_guard<std::mutex> guard(stream_mutex);
    stream_file.write(reinterpret_cast<const char *>(data), length);
    stream_bytes += length;
    ++stream_chunks;
}

int main(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "check") {
        if (!initialize_sdk()) return 2;
        const DWORD version = NET_DVR_GetSDKBuildVersion();
        NET_DVR_Cleanup();
        std::cout << "CAM_SDK_REPORT {\"sdk_build\":" << version
                  << ",\"initialized\":true,\"login_calls\":0,\"sdk_logging_enabled\":"
                  << (sdk_logging_enabled ? "true" : "false") << "}" << std::endl;
        return 0;
    }
    std::string host, port_string, username, password, seconds_string;
    if (!std::getline(std::cin, host) || !std::getline(std::cin, port_string) ||
        !std::getline(std::cin, username) || !std::getline(std::cin, password) ||
        !std::getline(std::cin, seconds_string)) return 2;
    NET_DVR_USER_LOGIN_INFO login{};
    if (host.empty() || username.empty() || password.empty() ||
        host.size() >= sizeof(login.sDeviceAddress) ||
        username.size() >= sizeof(login.sUserName) ||
        password.size() >= sizeof(login.sPassword)) {
        std::cout << "CAM_SDK_REPORT {\"error\":\"credential length invalid\",\"login_calls\":0}" << std::endl;
        return 2;
    }
    const int port = std::stoi(port_string);
    const int seconds = std::stoi(seconds_string);
    if (port < 1 || port > 65535 || seconds < 0 || seconds > 60) return 2;
    if (!initialize_sdk()) return 2;
    const DWORD version = NET_DVR_GetSDKBuildVersion();
    NET_DVR_SetConnectTime(5000, 1);
    NET_DVR_SetReconnect(0, FALSE);
    std::strncpy(login.sDeviceAddress, host.c_str(), sizeof(login.sDeviceAddress) - 1);
    std::strncpy(login.sUserName, username.c_str(), sizeof(login.sUserName) - 1);
    std::strncpy(login.sPassword, password.c_str(), sizeof(login.sPassword) - 1);
    login.wPort = static_cast<WORD>(port);
    login.bUseAsynLogin = FALSE;
    login.byLoginMode = 0; // Private SDK protocol only; no adaptive HTTP fallback.
    NET_DVR_DEVICEINFO_V40 device{};
    const auto started = std::chrono::steady_clock::now();
    // Deliberately one login call. Never loop, try a second password, or reconnect.
    const LONG user = NET_DVR_Login_V40(&login, &device);
    const DWORD error = user < 0 ? NET_DVR_GetLastError() : 0;
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started).count();
    std::ostringstream report;
    report << "CAM_SDK_REPORT {\"sdk_build\":" << version
              << ",\"sdk_logging_enabled\":" << (sdk_logging_enabled ? "true" : "false")
              << ",\"login_calls\":1,\"login_succeeded\":" << (user >= 0 ? "true" : "false")
              << ",\"sdk_error\":" << error << ",\"login_elapsed_ms\":" << elapsed;
    if (user < 0) {
        if (device.bySupportLock) {
            report << ",\"lock_reporting_supported\":true,\"remaining_login_attempts\":"
                      << static_cast<unsigned>(device.byRetryLoginTime)
                      << ",\"remaining_lock_seconds\":" << device.dwSurplusLockTime;
        }
        report << "}";
        std::cout << report.str() << std::endl;
        NET_DVR_Cleanup();
        return 2;
    }
    const auto &info = device.struDeviceV30;
    report << ",\"analog_channels\":" << static_cast<unsigned>(info.byChanNum)
              << ",\"analog_start_channel\":" << static_cast<unsigned>(info.byStartChan)
              << ",\"digital_channels\":" << static_cast<unsigned>(info.byIPChanNum) + 256u * info.byHighDChanNum
              << ",\"digital_start_channel\":" << static_cast<unsigned>(info.byStartDChan)
              << ",\"main_protocol\":" << static_cast<unsigned>(info.byMainProto)
              << ",\"sub_protocol\":" << static_cast<unsigned>(info.bySubProto);
    if (seconds > 0) {
        stream_file.open("/output/live-stream.bin", std::ios::binary | std::ios::trunc);
        NET_DVR_PREVIEWINFO preview{};
        preview.lChannel = info.byChanNum ? info.byStartChan : info.byStartDChan;
        preview.dwStreamType = 1; // Substream of the first reported channel.
        preview.dwLinkMode = 0; // TCP.
        preview.bBlocked = FALSE;
        preview.byProtoType = 0; // Private protocol.
        const LONG handle = stream_file ? NET_DVR_RealPlay_V40(user, &preview, on_stream, nullptr) : -1;
        const DWORD preview_error = handle < 0 ? NET_DVR_GetLastError() : 0;
        if (handle >= 0) {
            std::this_thread::sleep_for(std::chrono::seconds(seconds));
            NET_DVR_StopRealPlay(handle);
        }
        stream_file.close();
        report << ",\"preview_started\":" << (handle >= 0 ? "true" : "false")
                  << ",\"preview_error\":" << preview_error
                  << ",\"captured_bytes\":" << stream_bytes.load()
                  << ",\"captured_chunks\":" << stream_chunks.load();
    }
    report << "}";
    std::cout << report.str() << std::endl;
    NET_DVR_Logout(user);
    NET_DVR_Cleanup();
    return 0;
}
