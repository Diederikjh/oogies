#include "HCNetSDK.h"
#include "LinuxPlayM4.h"
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
static bool decode_requested = false;
static int player_port = -1;
static bool player_opened = false;
static bool player_started = false;
static bool secret_key_set = false;
static std::string verification_code;
static std::string capture_path;
static std::string decoder_error_stage;
static unsigned decoder_error = 0;
static std::atomic<unsigned long long> decoded_frames{0};
static std::atomic<unsigned long long> input_failures{0};
static std::atomic<int> frame_width{0}, frame_height{0};
static std::atomic<long> video_encryption{-1}, audio_encryption{-1}, encryption_key_present{-1};
static std::atomic<unsigned long long> encryption_events{0};
static std::mutex frame_mutex;
static bool frame_saved = false;
static unsigned system_header_bytes = 0;

static void CALLBACK on_decoded(int, char *data, int length, FRAME_INFO *info, void *, int) {
    if (!info || info->nType != T_YV12 || info->nWidth <= 0 || info->nHeight <= 0) return;
    const unsigned long long expected = 3ull * info->nWidth * info->nHeight / 2;
    if (expected != static_cast<unsigned>(length) || expected > 64ull * 1024 * 1024) return;
    frame_width = info->nWidth;
    frame_height = info->nHeight;
    ++decoded_frames;
    std::lock_guard<std::mutex> guard(frame_mutex);
    if (!frame_saved) {
        std::ofstream frame(capture_path + "/first-frame.yv12", std::ios::binary);
        frame.write(data, length);
        frame_saved = frame.good();
    }
}

static void CALLBACK on_encryption(int, ENCRYPT_INFO *info, void *, int) {
    if (!info) return;
    video_encryption = info->nVideoEncryptType;
    audio_encryption = info->nAudioEncryptType;
    encryption_key_present = info->nSetSecretKey;
    ++encryption_events;
}

static bool decoder_call(int success, const char *stage) {
    if (success) return true;
    if (decoder_error_stage.empty()) {
        decoder_error_stage = stage;
        decoder_error = PlayM4_GetLastError(player_port);
    }
    return false;
}

static bool prepare_decoder(const std::string &key) {
    if (!decoder_call(PlayM4_GetPort(&player_port), "GetPort")) return false;
    if (!decoder_call(PlayM4_SetStreamOpenMode(player_port, STREAME_REALTIME), "SetStreamOpenMode")) return false;
    // Matches the supplied Hik-Connect APK: full UTF-8 string, type 1, 128 bits.
    // The length parameter is not the string's byte count. Do not hash/truncate it.
    secret_key_set = decoder_call(PlayM4_SetSecretKey(player_port, 1,
                                 const_cast<char *>(key.c_str()), 128), "SetSecretKey");
    return secret_key_set;
}

static void close_decoder() {
    if (player_port < 0) return;
    if (player_started) PlayM4_Stop(player_port);
    if (player_opened) PlayM4_CloseStream(player_port);
    PlayM4_FreePort(player_port);
    player_port = -1;
}

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
    if (type == NET_DVR_SYSHEAD && system_header_bytes == 0) {
        std::ofstream header(capture_path + "/system-header.bin", std::ios::binary);
        header.write(reinterpret_cast<const char *>(data), length);
        system_header_bytes = length;
    }
    if (!decode_requested || !decoder_error_stage.empty()) return;
    if (type == NET_DVR_SYSHEAD && !player_opened) {
        player_opened = decoder_call(PlayM4_OpenStream(player_port, data, length, 4 * 1024 * 1024), "OpenStream");
        if (!player_opened) return;
        if (!decoder_call(PlayM4_SetEncryptTypeCallBack(player_port, 1, on_encryption, nullptr), "SetEncryptTypeCallBack") ||
            !decoder_call(PlayM4_SetDecCallBackExMend(player_port, on_decoded, nullptr, 0, nullptr), "SetDecCallBack")) return;
        player_started = decoder_call(PlayM4_Play(player_port, 0), "Play");
    } else if (type == NET_DVR_STREAMDATA && player_started) {
        if (!PlayM4_InputData(player_port, data, length)) {
            ++input_failures;
            decoder_call(FALSE, "InputData"); // No callback blocking or retry loop.
        }
    }
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) if (std::string(argv[i]) == "--decrypt") decode_requested = true;
    if (argc >= 2 && std::string(argv[1]) == "check") {
        if (!initialize_sdk()) return 2;
        const bool decoder_ready = !decode_requested || prepare_decoder("DUMMYVERIFICATION");
        close_decoder();
        const DWORD version = NET_DVR_GetSDKBuildVersion();
        NET_DVR_Cleanup();
        std::cout << "CAM_SDK_REPORT {\"sdk_build\":" << version
                  << ",\"initialized\":true,\"login_calls\":0,\"sdk_logging_enabled\":"
                  << (sdk_logging_enabled ? "true" : "false")
                  << ",\"decoder_checked\":" << (decode_requested ? "true" : "false")
                  << ",\"decoder_ready\":" << (decoder_ready ? "true" : "false")
                  << ",\"decoder_error_stage\":\"" << decoder_error_stage
                  << "\",\"decoder_error\":" << decoder_error << "}" << std::endl;
        return decoder_ready ? 0 : 2;
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
    if (decode_requested) {
        if (!std::getline(std::cin, verification_code) || verification_code.empty() ||
            verification_code.size() > 128 || verification_code.find_first_of("\r\n\0", 0, 3) != std::string::npos) return 2;
    }
    if (!initialize_sdk()) return 2;
    if (decode_requested) {
        if (!prepare_decoder(verification_code)) {
            close_decoder();
            NET_DVR_Cleanup();
            std::cout << "CAM_SDK_REPORT {\"login_calls\":0,\"decoder_error_stage\":\""
                      << decoder_error_stage << "\",\"decoder_error\":" << decoder_error << "}" << std::endl;
            return 2;
        }
    }
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
        close_decoder();
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
        const char *directory = std::getenv("CAM_SDK_CAPTURE_DIR");
        capture_path = directory ? directory : "/output";
        stream_file.open(capture_path + "/live-stream.bin", std::ios::binary | std::ios::trunc);
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
        close_decoder();
        stream_file.close();
        report << ",\"preview_started\":" << (handle >= 0 ? "true" : "false")
                  << ",\"preview_error\":" << preview_error
                  << ",\"captured_bytes\":" << stream_bytes.load()
                  << ",\"captured_chunks\":" << stream_chunks.load()
                  << ",\"system_header_bytes\":" << system_header_bytes;
        if (decode_requested) {
            report << ",\"verification_code_used\":" << (secret_key_set && player_opened ? "true" : "false")
                   << ",\"secret_key_set\":" << (secret_key_set ? "true" : "false")
                   << ",\"decoder_started\":" << (player_started ? "true" : "false")
                   << ",\"decoder_error_stage\":\"" << decoder_error_stage << "\""
                   << ",\"decoder_error\":" << decoder_error
                   << ",\"decoder_input_failures\":" << input_failures.load()
                   << ",\"decoded_video_frames\":" << decoded_frames.load()
                   << ",\"frame_width\":" << frame_width.load()
                   << ",\"frame_height\":" << frame_height.load()
                   << ",\"first_frame_saved\":" << (frame_saved ? "true" : "false")
                   << ",\"encryption_events\":" << encryption_events.load()
                   << ",\"video_encryption_type\":" << video_encryption.load()
                   << ",\"audio_encryption_type\":" << audio_encryption.load()
                   << ",\"decoder_key_present\":" << encryption_key_present.load();
        }
    }
    report << "}";
    std::cout << report.str() << std::endl;
    NET_DVR_Logout(user);
    NET_DVR_Cleanup();
    close_decoder();
    return decode_requested && (decoded_frames.load() == 0 || !decoder_error_stage.empty()) ? 2 : 0;
}
