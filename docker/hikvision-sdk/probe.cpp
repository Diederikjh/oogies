#include "HCNetSDK.h"
#include "LinuxPlayM4.h"
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

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
static bool historical_requested = false;
static bool skip_search = false;
static int clip_seconds = 0;
static std::ofstream clip_file;
static std::atomic<unsigned> clip_frames{0};
static std::atomic<bool> clip_complete{false}, clip_failed{false};
static int clip_fps = 0;
static int clip_width = 0, clip_height = 0;
static int first_clip_stamp = 0, last_clip_stamp = 0;
static bool browser_requested = false;
static volatile std::sig_atomic_t stop_requested = 0;
static std::mutex browser_frame_mutex;
static std::vector<char> browser_frame;
static int browser_width = 0, browser_height = 0;
static unsigned long long browser_sequence = 0, jpeg_frames = 0;

static void request_stop(int) { stop_requested = 1; }

static void CALLBACK on_decoded(int, char *data, int length, FRAME_INFO *info, void *, int) {
    if (!info || info->nType != T_YV12 || info->nWidth <= 0 || info->nHeight <= 0) return;
    const unsigned long long expected = 3ull * info->nWidth * info->nHeight / 2;
    if (expected != static_cast<unsigned>(length) || expected > 64ull * 1024 * 1024) return;
    frame_width = info->nWidth;
    frame_height = info->nHeight;
    ++decoded_frames;
    if (browser_requested) {
        std::lock_guard<std::mutex> guard(browser_frame_mutex);
        browser_frame.assign(data, data + length);
        browser_width = info->nWidth;
        browser_height = info->nHeight;
        ++browser_sequence;
        return;
    }
    std::lock_guard<std::mutex> guard(frame_mutex);
    if (!frame_saved) {
        std::ofstream frame(capture_path + "/first-frame.yv12", std::ios::binary);
        frame.write(data, length);
        frame_saved = frame.good();
    }
    if (historical_requested && !clip_complete && !clip_failed) {
        if (clip_frames == 0) {
            if (info->nFrameRate < 1 || info->nFrameRate > 60) { clip_failed = true; return; }
            clip_fps = info->nFrameRate;
            clip_width = info->nWidth;
            clip_height = info->nHeight;
            first_clip_stamp = info->nStamp;
        }
        if (clip_width != info->nWidth || clip_height != info->nHeight ||
            (clip_frames.load() + 1ull) * expected > 512ull * 1024 * 1024) {
            clip_failed = true;
            return;
        }
        clip_file.write(data, length);
        if (!clip_file.good()) { clip_failed = true; return; }
        last_clip_stamp = info->nStamp;
        ++clip_frames;
        if (clip_frames.load() >= static_cast<unsigned>(clip_seconds * clip_fps)) clip_complete = true;
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
    if (!decoder_call(PlayM4_SetStreamOpenMode(player_port, historical_requested ? STREAME_FILE : STREAME_REALTIME), "SetStreamOpenMode")) return false;
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
    if (!browser_requested) stream_file.write(reinterpret_cast<const char *>(data), length);
    stream_bytes += length;
    ++stream_chunks;
    if (type == NET_DVR_SYSHEAD && system_header_bytes == 0) {
        if (!browser_requested) {
            std::ofstream header(capture_path + "/system-header.bin", std::ios::binary);
            header.write(reinterpret_cast<const char *>(data), length);
        }
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

// Historical data arrives in bursts. Keep the SDK callback short and feed
// PlayCtrl from the main thread, with bounded buffering and input backpressure.
struct HistoryChunk { DWORD type; std::vector<BYTE> data; };
static std::deque<HistoryChunk> history_queue;
static std::mutex history_mutex;
static size_t history_queue_bytes = 0;
static std::atomic<bool> history_queue_overflow{false};

static void CALLBACK on_history(LONG, DWORD type, BYTE *data, DWORD length, void *) {
    if (type != NET_DVR_SYSHEAD && type != NET_DVR_STREAMDATA) return;
    std::lock_guard<std::mutex> guard(history_mutex);
    if (history_queue_bytes + length > 16 * 1024 * 1024) { history_queue_overflow = true; return; }
    history_queue.push_back({type, std::vector<BYTE>(data, data + length)});
    history_queue_bytes += length;
}

static std::time_t clock_value(const NET_DVR_TIME &value) {
    std::tm time{};
    time.tm_year = value.dwYear - 1900;
    time.tm_mon = value.dwMonth - 1;
    time.tm_mday = value.dwDay;
    time.tm_hour = value.dwHour;
    time.tm_min = value.dwMinute;
    time.tm_sec = value.dwSecond;
    // Calendar arithmetic on recorder wall time; do not apply the PC timezone.
    return timegm(&time);
}

static NET_DVR_TIME recorder_time(std::time_t value) {
    std::tm time{};
    gmtime_r(&value, &time);
    return {static_cast<DWORD>(time.tm_year + 1900), static_cast<DWORD>(time.tm_mon + 1),
            static_cast<DWORD>(time.tm_mday), static_cast<DWORD>(time.tm_hour),
            static_cast<DWORD>(time.tm_min), static_cast<DWORD>(time.tm_sec)};
}

static std::string time_text(const NET_DVR_TIME &value) {
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "%04u-%02u-%02uT%02u:%02u:%02u", value.dwYear,
                  value.dwMonth, value.dwDay, value.dwHour, value.dwMinute, value.dwSecond);
    return buffer;
}

static bool extract_history(LONG user, LONG channel, int seconds, std::ostringstream &report) {
    report << ",\"historical\":true,\"channel\":" << channel;
    auto failure = [&](const char *stage, DWORD error) {
        report << ",\"historical_error_stage\":\"" << stage << "\",\"historical_error\":" << error;
        return false;
    };
    NET_DVR_TIME now{};
    DWORD returned = 0;
    if (!NET_DVR_GetDVRConfig(user, NET_DVR_GET_TIMECFG, -1, &now, sizeof(now), &returned))
        return failure("read recorder clock", NET_DVR_GetLastError());
    if (returned < sizeof(now) || now.dwYear < 2020 || now.dwMonth < 1 || now.dwMonth > 12)
        return failure("invalid recorder clock", 17);
    const std::time_t desired = clock_value(now) - 3600;
    const NET_DVR_TIME begin = recorder_time(desired), end = recorder_time(desired + seconds);
    report << ",\"recorder_now\":\"" << time_text(now) << "\",\"requested_begin\":\""
           << time_text(begin) << "\",\"requested_end\":\"" << time_text(end) << "\"";
    NET_DVR_FINDDATA_V40 selected{};
    if (skip_search) report << ",\"search_skipped\":true,\"requested_stream_type\":0";
    else {
        NET_DVR_FILECOND_V40 conditions{};
        conditions.lChannel = channel;
        conditions.dwFileType = conditions.dwIsLocked = 0xff;
        conditions.byStreamType = 0xff;
        conditions.struStartTime = begin;
        conditions.struStopTime = end;
        const LONG search = NET_DVR_FindFile_V40(user, &conditions);
        if (search < 0) return failure("find recordings", NET_DVR_GetLastError());
        bool found = false;
        unsigned results = 0;
        LONG status = NET_DVR_ISFINDING;
        const auto search_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (std::chrono::steady_clock::now() < search_deadline && results < 100) {
            NET_DVR_FINDDATA_V40 item{};
            status = NET_DVR_FindNextFile_V40(search, &item);
            if (status == NET_DVR_ISFINDING) { std::this_thread::sleep_for(std::chrono::milliseconds(100)); continue; }
            if (status != NET_DVR_FILE_SUCCESS) break;
            ++results;
            if (clock_value(item.struStartTime) <= desired && clock_value(item.struStopTime) >= desired + seconds) {
                selected = item;
                found = true;
                break;
            }
        }
        NET_DVR_FindClose_V30(search);
        report << ",\"search_results_checked\":" << results << ",\"search_status\":" << status
               << ",\"recording_found\":" << (found ? "true" : "false");
        if (!found) return failure("no recording covering requested interval", 33);
        report << ",\"recording_begin\":\"" << time_text(selected.struStartTime)
               << "\",\"recording_end\":\"" << time_text(selected.struStopTime)
               << "\",\"recorded_stream_type\":" << static_cast<unsigned>(selected.byStreamType);
    }
    NET_DVR_VOD_PARA playback{};
    playback.dwSize = sizeof(playback);
    playback.struIDInfo.dwSize = sizeof(playback.struIDInfo);
    playback.struIDInfo.dwChannel = channel;
    playback.struBeginTime = begin;
    playback.struEndTime = end;
    playback.byStreamType = selected.byStreamType;
    const LONG handle = NET_DVR_PlayBackByTime_V40(user, &playback);
    if (handle < 0) return failure("create playback", NET_DVR_GetLastError());
    const char *directory = std::getenv("CAM_SDK_CAPTURE_DIR");
    capture_path = directory ? directory : "/output";
    clip_seconds = seconds;
    clip_file.open(capture_path + "/clip.yv12", std::ios::binary);
    stream_file.open(capture_path + "/historical-stream.bin", std::ios::binary);
    bool succeeded = false;
    if (!clip_file || !stream_file) failure("open capture files", 34);
    else if (!NET_DVR_SetPlayDataCallBack_V40(handle, on_history, nullptr)) failure("register playback callback", NET_DVR_GetLastError());
    else {
        DWORD offset = 0;
        if (!NET_DVR_PlayBackControl_V40(handle, NET_DVR_PLAYSTART, &offset, sizeof(offset), nullptr, nullptr))
            failure("start playback", NET_DVR_GetLastError());
        else {
            report << ",\"playback_started\":true";
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
            while (std::chrono::steady_clock::now() < deadline && !clip_complete && !clip_failed &&
                   !history_queue_overflow && decoder_error_stage.empty()) {
                HistoryChunk chunk;
                {
                    std::lock_guard<std::mutex> guard(history_mutex);
                    if (!history_queue.empty()) {
                        chunk = std::move(history_queue.front());
                        history_queue.pop_front();
                        history_queue_bytes -= chunk.data.size();
                    }
                }
                if (chunk.data.empty()) { std::this_thread::sleep_for(std::chrono::milliseconds(10)); continue; }
                if (chunk.type == NET_DVR_STREAMDATA && player_started) {
                    stream_file.write(reinterpret_cast<char *>(chunk.data.data()), chunk.data.size());
                    stream_bytes += chunk.data.size(); ++stream_chunks;
                    while (!PlayM4_InputData(player_port, chunk.data.data(), chunk.data.size())) {
                        const unsigned error = PlayM4_GetLastError(player_port);
                        if (error != PLAYM4_BUF_OVER || std::chrono::steady_clock::now() >= deadline || clip_complete) {
                            if (!clip_complete) decoder_call(FALSE, "InputData");
                            break;
                        }
                        ++input_failures;
                        std::this_thread::sleep_for(std::chrono::milliseconds(10));
                    }
                } else on_stream(handle, chunk.type, chunk.data.data(), chunk.data.size(), nullptr);
            }
            NET_DVR_TIME osd{};
            if (NET_DVR_GetPlayBackOsdTime(handle, &osd)) report << ",\"playback_osd_time\":\"" << time_text(osd) << "\"";
            succeeded = clip_complete && !clip_failed && !history_queue_overflow && decoder_error_stage.empty();
        }
    }
    NET_DVR_StopPlayBack(handle);
    close_decoder();
    clip_file.close(); stream_file.close();
    report << ",\"verification_code_used\":" << (secret_key_set && player_opened ? "true" : "false")
           << ",\"captured_bytes\":" << stream_bytes.load() << ",\"system_header_bytes\":" << system_header_bytes
           << ",\"decoded_video_frames\":" << decoded_frames.load() << ",\"clip_frames\":" << clip_frames.load()
           << ",\"clip_fps\":" << clip_fps << ",\"frame_width\":" << frame_width.load()
           << ",\"frame_height\":" << frame_height.load() << ",\"first_clip_stamp_ms\":" << first_clip_stamp
           << ",\"last_clip_stamp_ms\":" << last_clip_stamp << ",\"clip_complete\":" << (clip_complete ? "true" : "false")
           << ",\"clip_write_failed\":" << (clip_failed ? "true" : "false")
           << ",\"queue_overflow\":" << (history_queue_overflow ? "true" : "false")
           << ",\"decoder_error_stage\":\"" << decoder_error_stage << "\",\"decoder_error\":" << decoder_error
           << ",\"decoder_buffer_waits\":" << input_failures.load()
           << ",\"video_encryption_type\":" << video_encryption.load();
    return succeeded;
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--decrypt") decode_requested = true;
        if (std::string(argv[i]) == "--historical") historical_requested = true;
        if (std::string(argv[i]) == "--skip-search") skip_search = true;
        if (std::string(argv[i]) == "--browser-frames") browser_requested = true;
    }
    std::signal(SIGTERM, request_stop);
    std::signal(SIGINT, request_stop);
    if (argc >= 2 && std::string(argv[1]) == "check") {
        if (!initialize_sdk()) return 2;
        const bool decoder_ready = !decode_requested || prepare_decoder("DUMMYVERIFICATION");
        bool jpeg_ready = true;
        if (browser_requested) {
            std::vector<char> dummy(32 * 32 * 3 / 2, static_cast<char>(128));
            char filename[] = "/tmp/check-frame.jpg";
            jpeg_ready = PlayM4_ConvertToJpegFile(dummy.data(), dummy.size(), 32, 32, T_YV12, filename);
        }
        close_decoder();
        const DWORD version = NET_DVR_GetSDKBuildVersion();
        NET_DVR_Cleanup();
        std::cout << "CAM_SDK_REPORT {\"sdk_build\":" << version
                  << ",\"initialized\":true,\"login_calls\":0,\"sdk_logging_enabled\":"
                  << (sdk_logging_enabled ? "true" : "false")
                  << ",\"decoder_checked\":" << (decode_requested ? "true" : "false")
                  << ",\"decoder_ready\":" << (decoder_ready ? "true" : "false")
                  << ",\"jpeg_ready\":" << (jpeg_ready ? "true" : "false")
                  << ",\"decoder_error_stage\":\"" << decoder_error_stage
                  << "\",\"decoder_error\":" << decoder_error << "}" << std::endl;
        return decoder_ready && jpeg_ready ? 0 : 2;
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
    if (port < 1 || port > 65535 || seconds < 0 || seconds > (browser_requested ? 900 : 60)) return 2;
    if (browser_requested && (!decode_requested || historical_requested || seconds < 1)) return 2;
    if (historical_requested && (!decode_requested || seconds < 1 || seconds > 10)) return 2;
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
    if (historical_requested) {
        const bool extracted = extract_history(user, info.byChanNum ? info.byStartChan : info.byStartDChan, seconds, report);
        report << "}";
        std::cout << report.str() << std::endl;
        close_decoder();
        NET_DVR_Logout(user);
        NET_DVR_Cleanup();
        return extracted ? 0 : 2;
    }
    if (seconds > 0) {
        const char *directory = std::getenv("CAM_SDK_CAPTURE_DIR");
        capture_path = directory ? directory : "/output";
        if (!browser_requested) stream_file.open(capture_path + "/live-stream.bin", std::ios::binary | std::ios::trunc);
        NET_DVR_PREVIEWINFO preview{};
        preview.lChannel = info.byChanNum ? info.byStartChan : info.byStartDChan;
        preview.dwStreamType = 1; // Substream of the first reported channel.
        preview.dwLinkMode = 0; // TCP.
        preview.bBlocked = FALSE;
        preview.byProtoType = 0; // Private protocol.
        const LONG handle = (browser_requested || stream_file) ? NET_DVR_RealPlay_V40(user, &preview, on_stream, nullptr) : -1;
        const DWORD preview_error = handle < 0 ? NET_DVR_GetLastError() : 0;
        bool jpeg_failed = false;
        if (handle >= 0) {
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
            unsigned long long published = 0;
            while (!stop_requested && std::chrono::steady_clock::now() < deadline) {
                if (browser_requested) {
                    std::vector<char> frame;
                    int width = 0, height = 0;
                    unsigned long long sequence = 0;
                    {
                        std::lock_guard<std::mutex> guard(browser_frame_mutex);
                        if (browser_sequence != published) {
                            frame = browser_frame; width = browser_width; height = browser_height;
                            sequence = browser_sequence;
                        }
                    }
                    if (!frame.empty()) {
                        std::string temporary = capture_path + "/frame.tmp.jpg";
                        if (!PlayM4_ConvertToJpegFile(frame.data(), frame.size(), width, height, T_YV12, temporary.data()) ||
                            std::rename(temporary.c_str(), (capture_path + "/frame.jpg").c_str()) != 0) {
                            jpeg_failed = true;
                            break;
                        }
                        std::ofstream metadata(capture_path + "/frame.tmp.json");
                        metadata << "{\"sequence\":" << sequence << ",\"width\":" << width
                                 << ",\"height\":" << height << "}";
                        metadata.close();
                        std::rename((capture_path + "/frame.tmp.json").c_str(), (capture_path + "/frame.json").c_str());
                        published = sequence;
                        ++jpeg_frames;
                    }
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
            NET_DVR_StopRealPlay(handle);
        }
        if (jpeg_failed) { decoder_error_stage = "JPEG conversion"; decoder_error = 26; }
        close_decoder();
        stream_file.close();
        report << ",\"preview_started\":" << (handle >= 0 ? "true" : "false")
                  << ",\"preview_error\":" << preview_error
                  << ",\"captured_bytes\":" << stream_bytes.load()
                  << ",\"captured_chunks\":" << stream_chunks.load()
                  << ",\"system_header_bytes\":" << system_header_bytes;
        if (browser_requested) report << ",\"jpeg_frames\":" << jpeg_frames;
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
