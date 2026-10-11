// One independent time-playback handle and file-mode decoder per viewer.
#include "playback_buffer.h"

struct Playback {
    Source source;
    LONG handle = -1;
    bool paused = false, ended = false, error_reported = false, pause_on_frame = false;
    int rate_level = 0, desired_rate_level = 0;
    PlaybackBuffer buffer{16 * 1024 * 1024};
    NET_DVR_TIME end{};
    std::chrono::steady_clock::time_point last_status{}, last_frame{}, last_heartbeat{};

    Playback(const std::string &id, int generation, int channel, const std::string &root) : source(channel, root) {
        source.playback_id = id; source.directory = root + "/playback-" + id; source.generation = generation;
    }
    ~Playback() { close(); }

    void status(const std::string &state, unsigned error = 0) {
        event("{\"type\":\"playback\",\"id\":" + quote(source.playback_id) +
            ",\"generation\":" + std::to_string(source.generation) + ",\"state\":" + quote(state) +
            ",\"error\":" + std::to_string(error) + "}");
    }
    void close() {
        source.active = false;
        buffer.close();
        if (handle >= 0) NET_DVR_StopPlayBack(handle);
        handle = -1;
        stop(source);
    }
    static void CALLBACK received(LONG, DWORD type, BYTE *data, DWORD size, void *user) {
        auto *playback = static_cast<Playback *>(user);
        if (!playback->source.active || !size || (type != NET_DVR_SYSHEAD && type != NET_DVR_STREAMDATA)) return;
        if (playback->buffer.push(type, data, size) == PlaybackBuffer::Result::oversized)
            playback->source.error = 43;
    }
    static std::string rate_text(int level) { return level < 0 ? "0.5" : std::to_string(1 << level); }
    void apply_rate() {
        if (!source.playing || !source.active) return;
        const int requested = desired_rate_level;
        unsigned error = 0;
        while (rate_level != desired_rate_level) {
            const bool faster = rate_level < desired_rate_level;
            if (!(faster ? PlayM4_Fast(source.port) : PlayM4_Slow(source.port))) {
                error = PlayM4_GetLastError(source.port); desired_rate_level = rate_level; break;
            }
            rate_level += faster ? 1 : -1;
        }
        event("{\"type\":\"playback_rate\",\"id\":" + quote(source.playback_id) +
            ",\"generation\":" + std::to_string(source.generation) +
            ",\"rate\":" + rate_text(rate_level) + ",\"requested_rate\":" + rate_text(requested) +
            ",\"error\":" + std::to_string(error) + "}");
    }
    void set_rate(int level) {
        if (level < -1 || level > 2) return;
        desired_rate_level = level;
        apply_rate();
    }
    void start(LONG user, const std::string &key, NET_DVR_TIME begin, NET_DVR_TIME stop_time, bool initially_paused, int initial_rate_level) {
        desired_rate_level = initial_rate_level;
        end = stop_time;
        mkdir(source.directory.c_str(), 0700);
        if (!PlayM4_GetPort(&source.port) || !PlayM4_SetStreamOpenMode(source.port, STREAME_FILE) ||
            !PlayM4_SetSecretKey(source.port, 1, const_cast<char *>(key.c_str()), 128)) {
            source.error = source.port < 0 ? 41 : PlayM4_GetLastError(source.port);
        } else {
            NET_DVR_VOD_PARA parameters{};
            parameters.dwSize = sizeof(parameters); parameters.struIDInfo.dwSize = sizeof(parameters.struIDInfo);
            parameters.struIDInfo.dwChannel = source.channel;
            parameters.struBeginTime = begin; parameters.struEndTime = end; parameters.byStreamType = 0;
            source.active = true;
            handle = NET_DVR_PlayBackByTime_V40(user, &parameters);
            DWORD offset = 0;
            if (handle < 0 || !NET_DVR_SetPlayDataCallBack_V40(handle, received, this) ||
                !NET_DVR_PlayBackControl_V40(handle, NET_DVR_PLAYSTART, &offset, sizeof(offset), nullptr, nullptr))
                source.error = NET_DVR_GetLastError();
        }
        if (source.error) { status("error", source.error); error_reported = true; close(); }
        else {
            last_frame = std::chrono::steady_clock::now();
            status("starting");
            pause_on_frame = initially_paused;
        }
    }
    void pause(bool desired) {
        if (handle < 0 || ended || source.error) return;
        if (desired == paused) { status(paused ? "paused" : "playing"); return; }
        // Combined recorder/decoder pause failed on the verified SDK. Release
        // native resources, retain the browser's last frame, and let Python
        // resume by opening time playback at its confirmed recorded clock.
        if (desired) { close(); paused = true; status("paused"); }
    }
    void pump() {
        if (!source.active || paused || ended || source.error) return;
        const auto now = std::chrono::steady_clock::now();
        if (handle >= 0 && now - last_heartbeat >= std::chrono::seconds(2)) {
            // Hikvision recommends this while its data callback is blocked.
            NET_DVR_PlayBackControl_V40(handle, NET_DVR_KEEPALIVE, nullptr, 0, nullptr, nullptr);
            last_heartbeat = now;
            const auto stats = buffer.stats();
            event("{\"type\":\"playback_buffer\",\"id\":" + quote(source.playback_id) +
                ",\"generation\":" + std::to_string(source.generation) +
                ",\"queued_bytes\":" + std::to_string(stats.bytes) +
                ",\"high_water_bytes\":" + std::to_string(stats.high_water) +
                ",\"waits\":" + std::to_string(stats.waits) +
                ",\"received_bytes\":" + std::to_string(stats.received) + "}");
        }
        // Never wait for the decoder here: live publication and commands share
        // this thread. Retain refused chunks in order until its buffer drains.
        unsigned bytes = 0;
        while (bytes < 512 * 1024) {
            if (!buffer.consume([&](PlaybackBuffer::Chunk &chunk) {
                if (chunk.type == NET_DVR_STREAMDATA && source.playing) {
                    if (!PlayM4_InputData(source.port, chunk.data.data(), chunk.data.size())) {
                        const auto error = PlayM4_GetLastError(source.port);
                        if (error != PLAYM4_BUF_OVER) source.error = error;
                        return false;
                    }
                } else stream(handle, chunk.type, chunk.data.data(), chunk.data.size(), &source);
                if (source.playing && desired_rate_level != rate_level) apply_rate();
                bytes += chunk.data.size();
                return true;
            })) break;
            if (source.error) break;
        }
    }
    void publish_frame() {
        if (ended || paused) return;
        const auto previous = source.published;
        publish(source);
        const auto now = std::chrono::steady_clock::now();
        if (source.error) {
            if (!error_reported) status("error", source.error);
            error_reported = true; close(); return;
        }
        if (source.published != previous) {
            last_frame = now;
            if (pause_on_frame) { pause_on_frame = false; pause(true); return; }
        }
        if (handle < 0 || now - last_status < std::chrono::seconds(1)) return;
        last_status = now;
        DWORD progress = 0, returned = 0;
        bool complete = NET_DVR_PlayBackControl_V40(handle, NET_DVR_PLAYGETPOS, nullptr, 0, &progress, &returned) && progress == 100;
        const bool drained = buffer.stats().bytes == 0;
        if (complete && drained && source.playing && PlayM4_GetSourceBufferRemain(source.port) == 0 &&
            PlayM4_GetBufferValue(source.port, BUF_VIDEO_DECODED) == 0 && now - last_frame > std::chrono::seconds(1)) {
            ended = true; status("ended"); close();
        } else if (now - last_frame > std::chrono::seconds(15)) {
            source.error = 33; status("error", 33); error_reported = true; close();
        }
    }
};
