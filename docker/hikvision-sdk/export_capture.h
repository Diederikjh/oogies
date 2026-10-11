// Every decoded frame goes through a bounded pipe to the Python encoder.
// This context shares login, but owns its playback handle, decoder and thread.
#include <fcntl.h>
#include <cerrno>

struct ExportCapture {
    Playback playback;
    PlaybackBuffer frames{16 * 1024 * 1024};
    std::atomic<bool> cancelled{false}, done{false};
    std::thread thread;
    size_t written = 0;
    int fd = -1;
    std::chrono::steady_clock::time_point last_frame = std::chrono::steady_clock::now();

    ExportCapture(const std::string &id, int channel, LONG user, const std::string &key,
                  NET_DVR_TIME begin, NET_DVR_TIME end) : playback(id, 1, channel, "/exports") {
        playback.source.directory = "/exports/" + id;
        playback.source.capture = [this](char *data, int size, FRAME_INFO *info) {
            PLAYM4_SYSTEM_TIME clock{};
            const bool valid = PlayM4_GetSystemTime(playback.source.port, &clock) && clock.dwYear >= 2000 && clock.dwYear <= 2100;
            NET_DVR_TIME wall{clock.dwYear, clock.dwMon, clock.dwDay, clock.dwHour, clock.dwMin, clock.dwSec};
            std::ostringstream header;
            header << "{\"size\":" << size << ",\"width\":" << info->nWidth << ",\"height\":" << info->nHeight
                << ",\"fps\":" << info->nFrameRate << ",\"stamp\":" << static_cast<unsigned>(info->nStamp)
                << ",\"position\":" << (valid ? quote(history_time(wall)) : "null") << ",\"ms\":" << clock.dwMs << "}\n";
            const auto text = header.str();
            std::vector<unsigned char> packet(text.begin(), text.end());
            packet.insert(packet.end(), data, data + size);
            if (frames.push(0, packet.data(), packet.size()) == PlaybackBuffer::Result::oversized) playback.source.error = 43;
        };
        thread = std::thread([this, user, key, begin, end, id]() {
            // Python opens the reader before requesting capture. Never block
            // SDK/main-thread shutdown on an absent or stalled reader.
            fd = open((playback.source.directory + "/frames.pipe").c_str(), O_WRONLY | O_NONBLOCK);
            if (fd < 0) playback.source.error = 26;
            else playback.start(user, key, begin, end, false, 0);
            auto last_status = std::chrono::steady_clock::now();
            while (!cancelled && !playback.source.error && playback.source.active) {
                playback.pump();
                while (frames.consume([&](PlaybackBuffer::Chunk &chunk) {
                    const auto count = write(fd, chunk.data.data() + written, chunk.data.size() - written);
                    if (count < 0) {
                        if (errno != EAGAIN && errno != EINTR) playback.source.error = 26;
                        return false;
                    }
                    written += count; last_frame = std::chrono::steady_clock::now();
                    if (written != chunk.data.size()) return false;
                    written = 0; return true;
                })) {}
                const auto now = std::chrono::steady_clock::now();
                if (now - last_status >= std::chrono::seconds(1)) {
                    last_status = now;
                    DWORD progress = 0, returned = 0;
                    const bool complete = NET_DVR_PlayBackControl_V40(playback.handle, NET_DVR_PLAYGETPOS, nullptr, 0, &progress, &returned) && progress == 100;
                    if (complete && playback.buffer.stats().bytes == 0 && frames.stats().bytes == 0 && playback.source.playing &&
                        PlayM4_GetSourceBufferRemain(playback.source.port) == 0 &&
                        PlayM4_GetBufferValue(playback.source.port, BUF_VIDEO_DECODED) == 0 && now - last_frame > std::chrono::seconds(1)) break;
                }
                // Python owns duration/stall checks and stops capture once the
                // first frame at the exclusive end has been received.
                if (std::chrono::steady_clock::now() - last_frame > std::chrono::seconds(20)) playback.source.error = 33;
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
            frames.close(); playback.close();
            if (fd >= 0) { ::close(fd); fd = -1; }
            event("{\"type\":\"export\",\"id\":" + quote(id) + ",\"error\":" + std::to_string(playback.source.error.load()) + "}");
            done = true;
        });
    }
    ~ExportCapture() {
        cancelled = true; frames.close(); playback.buffer.close();
        if (thread.joinable()) thread.join();
    }
};
