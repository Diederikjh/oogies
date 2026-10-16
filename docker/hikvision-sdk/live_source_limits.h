#pragma once
#include <cstdint>
#include <string>

// HCNetSDK 6.1.9.48 NET_DVR_PREVIEWINFO: main=0, substream=1.
inline int live_stream_type(const std::string &quality) {
    return quality == "high" ? 0 : quality == "overview" ? 1 : -1;
}

inline bool valid_live_frame(int width, int height, int size) {
    return width > 0 && height > 0 && width <= 4096 && height <= 4096 &&
        width % 2 == 0 && height % 2 == 0 && size > 0 &&
        3ull * width * height / 2 == static_cast<unsigned>(size) && size <= 16 * 1024 * 1024;
}
