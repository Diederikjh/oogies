#include "HCNetSDK.h"
#include "LinuxPlayM4.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <poll.h>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

static volatile std::sig_atomic_t stopping = 0;
static void interrupt(int) { stopping = 1; }
static std::string quote(const std::string &value) {
    std::ostringstream out; out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u00" << "0123456789abcdef"[c >> 4] << "0123456789abcdef"[c & 15];
        else out << c;
    }
    out << '"'; return out.str();
}
static std::mutex event_mutex;
static void event(const std::string &json) {
    std::lock_guard<std::mutex> guard(event_mutex);
    std::cout << "GRID_EVENT " << json << std::endl;
}
#include "history_queries.h"
static bool line(std::string &value) {
    value.clear(); char c;
    while (!stopping && value.size() <= 512) {
        const auto count = read(STDIN_FILENO, &c, 1);
        if (count <= 0) return false;
        if (c == '\n') return true;
        value += c;
    }
    return false;
}
static bool initialize() {
    NET_DVR_LOCAL_SDK_PATH path{};
    std::strncpy(path.sPath, "/sdk/lib", sizeof(path.sPath) - 1);
    char crypto[] = "/sdk/lib/libcrypto.so.1.1", tls[] = "/sdk/lib/libssl.so.1.1";
    return NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, &path) &&
        NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_LIBEAY_PATH, crypto) &&
        NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SSLEAY_PATH, tls) && NET_DVR_Init();
}

struct Source {
    int channel, generation = 0, port = -1;
    LONG preview = -1;
    bool opened = false, playing = false;
    std::atomic<bool> active{false};
    std::atomic<unsigned> error{0};
    std::atomic<unsigned long long> decoded{0};
    std::mutex input, frames;
    std::vector<char> latest;
    int width = 0, height = 0;
    unsigned long long sequence = 0, published = 0, jpegs = 0;
    std::string directory;
    std::string playback_id, position;
    explicit Source(int ch, const std::string &root) : channel(ch), directory(root + "/camera-" + std::to_string(ch)) {}
};

static void CALLBACK decoded(int, char *data, int size, FRAME_INFO *info, void *user, int) {
    auto *source = static_cast<Source *>(user);
    if (!source || !source->active || !info || info->nType != T_YV12 || info->nWidth <= 0 || info->nHeight <= 0) return;
    const auto expected = 3ull * info->nWidth * info->nHeight / 2;
    if (expected != static_cast<unsigned>(size) || expected > 4ull * 1024 * 1024) { source->error = 17; return; }
    std::lock_guard<std::mutex> guard(source->frames);
    source->latest.assign(data, data + size);
    source->width = info->nWidth; source->height = info->nHeight;
    ++source->sequence; ++source->decoded;
}
static void CALLBACK stream(LONG, DWORD type, BYTE *data, DWORD size, void *user) {
    auto *source = static_cast<Source *>(user);
    if (!source || !source->active || source->error) return;
    std::lock_guard<std::mutex> guard(source->input);
    if (!source->active || source->error) return;
    if (type == NET_DVR_SYSHEAD && !source->opened) {
        source->opened = PlayM4_OpenStream(source->port, data, size, 4 * 1024 * 1024);
        if (!source->opened || !PlayM4_SetDecCallBackExMend(source->port, decoded, nullptr, 0, source)) {
            source->error = PlayM4_GetLastError(source->port); return;
        }
        source->playing = PlayM4_Play(source->port, 0);
        if (!source->playing) source->error = PlayM4_GetLastError(source->port);
    } else if (type == NET_DVR_STREAMDATA && source->playing && !PlayM4_InputData(source->port, data, size)) {
        source->error = PlayM4_GetLastError(source->port);
    }
}
static void stop(Source &source) {
    source.active = false;
    if (source.preview >= 0) NET_DVR_StopRealPlay(source.preview);
    source.preview = -1;
    std::lock_guard<std::mutex> guard(source.input);
    if (source.playing) PlayM4_Stop(source.port);
    if (source.opened) PlayM4_CloseStream(source.port);
    if (source.port >= 0) PlayM4_FreePort(source.port);
    source.port = -1; source.opened = source.playing = false;
    std::lock_guard<std::mutex> frame_guard(source.frames);
    source.latest.clear();
}
static void start(Source &source, LONG user, const std::string &key) {
    if (source.active) return;
    stop(source);
    ++source.generation; source.error = 0;
    source.decoded = 0; source.jpegs = source.sequence = source.published = 0;
    mkdir(source.directory.c_str(), 0700);
    if (!PlayM4_GetPort(&source.port) || !PlayM4_SetStreamOpenMode(source.port, STREAME_REALTIME) ||
        !PlayM4_SetSecretKey(source.port, 1, const_cast<char *>(key.c_str()), 128)) {
        source.error = source.port < 0 ? 1 : PlayM4_GetLastError(source.port);
    } else {
        source.active = true;
        NET_DVR_PREVIEWINFO info{};
        info.lChannel = source.channel; info.dwStreamType = 1;
        info.dwLinkMode = 0; info.bBlocked = FALSE; info.byProtoType = 0;
        source.preview = NET_DVR_RealPlay_V40(user, &info, stream, &source);
        if (source.preview < 0) source.error = NET_DVR_GetLastError();
    }
    std::ostringstream out;
    out << "{\"type\":\"started\",\"channel\":" << source.channel << ",\"generation\":" << source.generation
        << ",\"error\":" << source.error.load() << "}";
    event(out.str());
    if (source.error) stop(source);
}
static void publish(Source &source) {
    if (!source.active) return;
    if (source.error) {
        if (source.playback_id.empty())
            event("{\"type\":\"source_error\",\"channel\":" + std::to_string(source.channel) + ",\"error\":" + std::to_string(source.error.load()) + "}");
        stop(source); return;
    }
    std::vector<char> frame; int width, height; unsigned long long sequence;
    {
        std::lock_guard<std::mutex> guard(source.frames);
        if (source.sequence == source.published) return;
        frame = source.latest; width = source.width; height = source.height; sequence = source.sequence;
    }
    std::string temporary = source.directory + "/frame.tmp.jpg";
    if (!PlayM4_ConvertToJpegFile(frame.data(), frame.size(), width, height, T_YV12, temporary.data()) ||
        std::rename(temporary.c_str(), (source.directory + "/frame.jpg").c_str()) != 0) {
        source.error = 26; return;
    }
    ++source.jpegs;
    if (!source.playback_id.empty()) {
        PLAYM4_SYSTEM_TIME clock{};
        if (PlayM4_GetSystemTime(source.port, &clock) && clock.dwYear >= 2000 && clock.dwYear <= 2100) {
            NET_DVR_TIME wall{clock.dwYear, clock.dwMon, clock.dwDay, clock.dwHour, clock.dwMin, clock.dwSec};
            source.position = history_time(wall);
        }
    }
    std::ofstream metadata(source.directory + "/frame.tmp.json");
    metadata << "{\"generation\":" << source.generation << ",\"sequence\":" << sequence
        << ",\"width\":" << width << ",\"height\":" << height << ",\"decoded_frames\":" << source.decoded.load()
        << ",\"jpeg_frames\":" << source.jpegs << ",\"position\":"
        << (source.position.empty() ? "null" : quote(source.position)) << "}";
    metadata.close();
    std::rename((source.directory + "/frame.tmp.json").c_str(), (source.directory + "/frame.json").c_str());
    source.published = sequence;
}

#include "history_playback.h"

struct Camera { int channel; std::string name, online; };
static std::vector<Camera> discover(LONG user, const NET_DVR_DEVICEINFO_V30 &device, bool read_names = true) {
    NET_DVR_WORKSTATE_V30 state{};
    bool state_ok = NET_DVR_GetDVRWorkState_V30(user, &state);
    NET_DVR_IPPARACFG_V40 ip{}; ip.dwSize = sizeof(ip); DWORD returned = 0;
    bool ip_ok = NET_DVR_GetDVRConfig(user, NET_DVR_GET_IPPARACFG_V40, 0, &ip, sizeof(ip), &returned);
    std::vector<Camera> cameras;
    auto add = [&](int channel, bool online_known, bool online) {
        NET_DVR_PICCFG_V30 picture{}; picture.dwSize = sizeof(picture);
        std::string name = "Camera " + std::to_string(channel);
        if (read_names && NET_DVR_GetDVRConfig(user, NET_DVR_GET_PICCFG_V30, channel, &picture, sizeof(picture), &returned)) {
            const auto length = strnlen(reinterpret_cast<const char *>(picture.sChanName), NAME_LEN);
            if (length) name.assign(reinterpret_cast<const char *>(picture.sChanName), length);
        }
        cameras.push_back({channel, name, online_known ? (online ? "true" : "false") : "null"});
    };
    for (unsigned i = 0; i < device.byChanNum && i < 64; ++i) {
        if (ip_ok && !ip.byAnalogChanEnable[i]) continue;
        const int channel = device.byStartChan + i;
        const int index = channel - 1;
        const bool known = state_ok && index >= 0 && index < MAX_CHANNUM_V30;
        add(channel, known, known && state.struChanStatic[index].bySignalStatic == 0 && state.struChanStatic[index].byHardwareStatic == 0);
    }
    if (ip_ok) {
        const unsigned total = std::min<unsigned>(ip.dwDChanNum, 512);
        for (unsigned group = 0; group * 64 < total; ++group) {
            if (group && !NET_DVR_GetDVRConfig(user, NET_DVR_GET_IPPARACFG_V40, group, &ip, sizeof(ip), &returned)) break;
            for (unsigned i = 0; i < 64 && group * 64 + i < total; ++i) {
                auto &mode = ip.struStreamMode[i]; bool configured = false, online = false, known = false;
                if (mode.byGetStreamType == 0) {
                    configured = mode.uGetStream.struChanInfo.byIPID || mode.uGetStream.struChanInfo.byIPIDHigh;
                    online = mode.uGetStream.struChanInfo.byEnable; known = true;
                } else if (mode.byGetStreamType == 6) {
                    configured = mode.uGetStream.struIPChan.wIPID;
                    online = mode.uGetStream.struIPChan.byEnable; known = true;
                }
                if (configured) add(ip.dwStartDChan + group * 64 + i, known, online);
            }
        }
    }
    return cameras;
}

int main(int argc, char **argv) {
    std::signal(SIGTERM, interrupt); std::signal(SIGINT, interrupt);
    if (!initialize()) { event("{\"type\":\"fatal\",\"error\":" + std::to_string(NET_DVR_GetLastError()) + "}"); return 2; }
    if (argc > 1 && std::string(argv[1]) == "check") {
        int port = -1; std::string key = "DUMMYVERIFICATION";
        bool ok = PlayM4_GetPort(&port) && PlayM4_SetStreamOpenMode(port, STREAME_REALTIME) &&
            PlayM4_SetSecretKey(port, 1, key.data(), 128);
        if (port >= 0) PlayM4_FreePort(port);
        NET_DVR_Cleanup(); event(std::string("{\"type\":\"check\",\"login_calls\":0,\"decoder_ready\":") + (ok ? "true}" : "false}"));
        return ok ? 0 : 2;
    }
    std::string host, port, username, password, duration, key;
    if (!line(host) || !line(port) || !line(username) || !line(password) || !line(duration) || !line(key)) { NET_DVR_Cleanup(); return 2; }
    NET_DVR_USER_LOGIN_INFO login{};
    if (host.empty() || host.size() >= sizeof(login.sDeviceAddress) || username.empty() || username.size() >= sizeof(login.sUserName) ||
        password.empty() || password.size() >= sizeof(login.sPassword) || key.empty() || key.size() > 128) { NET_DVR_Cleanup(); return 2; }
    std::strncpy(login.sDeviceAddress, host.c_str(), sizeof(login.sDeviceAddress) - 1);
    std::strncpy(login.sUserName, username.c_str(), sizeof(login.sUserName) - 1);
    std::strncpy(login.sPassword, password.c_str(), sizeof(login.sPassword) - 1);
    try { const int value = std::stoi(port); if (value < 1 || value > 65535) return 2; login.wPort = value; } catch (...) { return 2; }
    NET_DVR_SetConnectTime(5000, 1); NET_DVR_SetReconnect(0, FALSE);
    NET_DVR_DEVICEINFO_V40 device{};
    const LONG user = NET_DVR_Login_V40(&login, &device);
    if (user < 0) { event("{\"type\":\"fatal\",\"login_calls\":1,\"error\":" + std::to_string(NET_DVR_GetLastError()) + "}"); NET_DVR_Cleanup(); return 2; }
    const auto cameras = discover(user, device.struDeviceV30);
    std::ostringstream ready;
    ready << "{\"type\":\"ready\",\"protocol\":1,\"login_calls\":1,\"sdk_build\":" << NET_DVR_GetSDKBuildVersion() << ",\"cameras\":[";
    for (unsigned i = 0; i < cameras.size(); ++i) {
        if (i) ready << ',';
        ready << "{\"channel\":" << cameras[i].channel << ",\"name\":" << quote(cameras[i].name) << ",\"online\":" << cameras[i].online << "}";
    }
    ready << "]}"; event(ready.str());
    const char *root = std::getenv("CAM_SDK_CAPTURE_DIR");
    if (!root) { NET_DVR_Logout(user); NET_DVR_Cleanup(); return 2; }
    std::map<int, std::unique_ptr<Source>> sources;
    std::map<std::string, std::unique_ptr<Playback>> playbacks;
    for (const auto &camera : cameras) sources[camera.channel] = std::make_unique<Source>(camera.channel, root);
    std::string buffer;
    std::thread history_job;
    std::atomic<bool> history_busy{false};
    auto last_publish = std::chrono::steady_clock::now();
    while (!stopping) {
        pollfd descriptor{STDIN_FILENO, POLLIN, 0};
        if (poll(&descriptor, 1, 20) > 0) {
            char data[1024]; const auto count = read(STDIN_FILENO, data, sizeof(data));
            if (count <= 0) break;
            buffer.append(data, count);
            if (buffer.size() > 8192) break;
            size_t newline;
            while ((newline = buffer.find('\n')) != std::string::npos) {
                std::istringstream command(buffer.substr(0, newline)); buffer.erase(0, newline + 1);
                std::string operation; int channel = 0; command >> operation >> channel;
                if (operation == "quit") { stopping = 1; break; }
                if (operation.rfind("playback-", 0) == 0) {
                    std::string id; int generation = 0; command >> id >> generation;
                    if (id.size() != 32 || id.find_first_not_of("0123456789abcdef") != std::string::npos || generation < 1) continue;
                    if (operation == "playback-start") {
                        std::string begin_text, end_text; int paused = 0; command >> begin_text >> end_text >> paused;
                        NET_DVR_TIME begin{}, end{};
                        if (!sources.count(channel) || !parse_history_time(begin_text, begin) || !parse_history_time(end_text, end)) continue;
                        if (playbacks.count(id)) playbacks.erase(id);
                        if (playbacks.size() >= 8) {
                            event("{\"type\":\"playback\",\"id\":" + quote(id) + ",\"generation\":" + std::to_string(generation) + ",\"state\":\"error\",\"error\":41}");
                            continue;
                        }
                        auto playback = std::make_unique<Playback>(id, generation, channel, root);
                        playback->start(user, key, begin, end, paused != 0);
                        playbacks[id] = std::move(playback);
                    } else if (playbacks.count(id) && playbacks[id]->source.generation == generation) {
                        if (operation == "playback-stop") playbacks.erase(id);
                        else if (operation == "playback-pause") playbacks[id]->pause(true);
                        else if (operation == "playback-resume") playbacks[id]->pause(false);
                    }
                    continue;
                }
                if (operation == "timeline") {
                    std::string id, begin_text, end_text; command >> id >> begin_text >> end_text;
                    NET_DVR_TIME begin{}, end{};
                    if (!sources.count(channel) || id.size() != 32 ||
                        id.find_first_not_of("0123456789abcdef") != std::string::npos ||
                        !parse_history_time(begin_text, begin) || !parse_history_time(end_text, end)) continue;
                    if (history_busy) {
                        event("{\"type\":\"timeline\",\"id\":" + quote(id) + ",\"busy\":true}"); continue;
                    }
                    if (history_job.joinable()) history_job.join();
                    history_busy = true;
                    history_job = std::thread([&, id, channel, begin, end]() {
                        history_query(user, id, channel, begin, end); history_busy = false;
                    });
                    continue;
                }
                if (operation == "refresh") {
                    const auto availability = discover(user, device.struDeviceV30, false);
                    std::ostringstream update; update << "{\"type\":\"availability\",\"cameras\":[";
                    bool first = true;
                    for (const auto &camera : availability) {
                        if (!sources.count(camera.channel)) continue;
                        if (!first) update << ',';
                        first = false;
                        update << "{\"channel\":" << camera.channel << ",\"online\":" << camera.online << "}";
                    }
                    update << "]}"; event(update.str());
                    continue;
                }
                if (!sources.count(channel)) continue;
                if (operation == "start") {
                    unsigned active = 0; for (auto &item : sources) active += item.second->active ? 1 : 0;
                    if (active < 16) start(*sources[channel], user, key);
                } else if (operation == "stop") {
                    stop(*sources[channel]);
                    event("{\"type\":\"stopped\",\"channel\":" + std::to_string(channel) + "}");
                }
            }
        }
        if (std::chrono::steady_clock::now() - last_publish >= std::chrono::milliseconds(100)) {
            for (auto &item : sources) publish(*item.second);
            for (auto &item : playbacks) item.second->publish_frame();
            last_publish = std::chrono::steady_clock::now();
        }
        for (auto &item : playbacks) item.second->pump();
    }
    for (auto &item : sources) stop(*item.second);
    playbacks.clear();
    if (history_job.joinable()) history_job.join();
    NET_DVR_Logout(user); NET_DVR_Cleanup();
    event("{\"type\":\"shutdown\",\"login_calls\":1}");
    return 0;
}
