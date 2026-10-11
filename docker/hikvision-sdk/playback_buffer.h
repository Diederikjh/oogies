#pragma once
#include <algorithm>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <vector>

// A decoder refusal leaves the front chunk counted against the limit. The SDK
// callback waits before copying another chunk; close wakes it before SDK stop.
class PlaybackBuffer {
public:
    struct Chunk { unsigned type; std::vector<unsigned char> data; };
    enum class Result { accepted, closed, oversized };
    struct Stats { size_t bytes, high_water, waits, waiting, received; };
    explicit PlaybackBuffer(size_t limit) : limit_(limit) {}

    Result push(unsigned type, const unsigned char *data, size_t size) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (closed_) return Result::closed;
        if (size > limit_) return Result::oversized;
        if (size > limit_ - bytes_) {
            ++waits_; ++waiting_;
            room_.wait(lock, [&] { return closed_ || size <= limit_ - bytes_; });
            --waiting_;
        }
        if (closed_) return Result::closed;
        chunks_.push_back({type, std::vector<unsigned char>(data, data + size)});
        bytes_ += size; received_ += size;
        high_water_ = std::max(high_water_, bytes_);
        return Result::accepted;
    }

    // accept must return promptly: false means the decoder is temporarily full.
    template<class Accept> bool consume(Accept accept) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (closed_ || chunks_.empty() || !accept(chunks_.front())) return false;
        bytes_ -= chunks_.front().data.size(); chunks_.pop_front();
        lock.unlock(); room_.notify_all(); return true;
    }
    Stats stats() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return {bytes_, high_water_, waits_, waiting_, received_};
    }
    void close() {
        { std::lock_guard<std::mutex> lock(mutex_);
          closed_ = true; chunks_.clear(); bytes_ = 0; }
        room_.notify_all();
    }
private:
    const size_t limit_;
    mutable std::mutex mutex_;
    std::condition_variable room_;
    std::deque<Chunk> chunks_;
    size_t bytes_ = 0, high_water_ = 0, waits_ = 0, waiting_ = 0, received_ = 0;
    bool closed_ = false;
};
