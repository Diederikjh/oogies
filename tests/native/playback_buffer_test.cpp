#include "playback_buffer.h"
#include <cassert>
#include <chrono>
#include <future>
#include <string>
#include <thread>

using namespace std::chrono_literals;
static void waiting(PlaybackBuffer &buffer) {
    const auto deadline = std::chrono::steady_clock::now() + 2s;
    while (!buffer.stats().waiting && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(1ms);
    assert(buffer.stats().waiting == 1);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    unsigned char data[8]{};
    PlaybackBuffer buffer(8);
    assert(buffer.push(1, data, 8) == PlaybackBuffer::Result::accepted);
    if (scenario == "refusal") {
        auto producer = std::async(std::launch::async, [&] { return buffer.push(2, data, 8); });
        waiting(buffer);
        assert(!buffer.consume([](auto &chunk) { assert(chunk.type == 1); return false; }));
        assert(buffer.stats().bytes == 8);
        assert(producer.wait_for(20ms) == std::future_status::timeout);
        assert(buffer.consume([](auto &chunk) { assert(chunk.type == 1); return true; }));
        assert(producer.wait_for(2s) == std::future_status::ready);
        assert(producer.get() == PlaybackBuffer::Result::accepted);
        assert(buffer.consume([](auto &chunk) { assert(chunk.type == 2); return true; }));
        assert(buffer.stats().high_water == 8 && buffer.stats().bytes == 0);
    } else if (scenario == "cancel") {
        auto producer = std::async(std::launch::async, [&] { return buffer.push(2, data, 8); });
        waiting(buffer);
        buffer.close();
        assert(producer.wait_for(2s) == std::future_status::ready);
        assert(producer.get() == PlaybackBuffer::Result::closed);
        assert(buffer.push(3, data, 8) == PlaybackBuffer::Result::closed);
        assert(buffer.stats().bytes == 0 && buffer.stats().waiting == 0);
    } else if (scenario == "burst") {
        assert(buffer.consume([](auto &) { return true; }));
        assert(buffer.push(1, data, 9) == PlaybackBuffer::Result::oversized);
        auto producer = std::async(std::launch::async, [&] {
            for (unsigned i = 0; i < 500; ++i)
                assert(buffer.push(i, data, 8) == PlaybackBuffer::Result::accepted);
        });
        waiting(buffer);
        for (unsigned expected = 0; expected < 500;) {
            // Mimic a decoder refusing input while its pool is full.
            assert(!buffer.consume([](auto &) { return false; }));
            if (buffer.consume([&](auto &chunk) {
                assert(chunk.type == expected && chunk.data.size() == 8); return true;
            })) ++expected;
            std::this_thread::sleep_for(1ms);
        }
        assert(producer.wait_for(2s) == std::future_status::ready); producer.get();
        const auto stats = buffer.stats();
        assert(stats.bytes == 0 && stats.high_water == 8 && stats.waits > 0);
        assert(stats.received == 8 * 501);
    } else return 2;
}
