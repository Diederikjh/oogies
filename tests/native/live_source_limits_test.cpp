#include "live_source_limits.h"
#include <cassert>
#include <climits>

int main() {
    assert(live_stream_type("overview") == 1);
    assert(live_stream_type("high") == 0);
    assert(live_stream_type("invalid") == -1);
    assert(valid_live_frame(352, 288, 352 * 288 * 3 / 2));
    assert(valid_live_frame(1920, 1080, 1920 * 1080 * 3 / 2));
    assert(valid_live_frame(3840, 2160, 3840 * 2160 * 3 / 2));
    assert(!valid_live_frame(4096, 4096, 4096 * 4096 * 3 / 2));
    assert(!valid_live_frame(INT_MAX, INT_MAX, INT_MAX));
    assert(!valid_live_frame(1920, 1080, -1));
    assert(!valid_live_frame(1920, 1080, 1920 * 1080));
    assert(!valid_live_frame(1919, 1080, 1919 * 1080 * 3 / 2));
    assert(!valid_live_frame(0, 1080, 0));
}
