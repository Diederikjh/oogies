// HCNetSDK-specific historical metadata. Times here are recorder wall time;
// the Python boundary owns timezone conversion and public interval IDs.+#include <ctime>
#include <iomanip>
#include <thread>

static std::string history_time(const NET_DVR_TIME &time) {
    char value[32];
    std::snprintf(value, sizeof(value), "%04u-%02u-%02uT%02u:%02u:%02u",
        time.dwYear, time.dwMonth, time.dwDay, time.dwHour, time.dwMinute, time.dwSecond);
    return value;
}
static bool parse_history_time(const std::string &value, NET_DVR_TIME &time) {
    std::tm parsed{}; std::istringstream input(value);
    input >> std::get_time(&parsed, "%Y-%m-%dT%H:%M:%S");
    if (input.fail() || value.size() != 19 || parsed.tm_year < 100 ||
        parsed.tm_year > 200 || parsed.tm_sec > 59) return false;
    time = {static_cast<DWORD>(parsed.tm_year + 1900), static_cast<DWORD>(parsed.tm_mon + 1),
        static_cast<DWORD>(parsed.tm_mday), static_cast<DWORD>(parsed.tm_hour),
        static_cast<DWORD>(parsed.tm_min), static_cast<DWORD>(parsed.tm_sec)};
    return true;
}

static std::string history_search(LONG user, int channel, const NET_DVR_TIME &begin,
                                  const NET_DVR_TIME &end, bool motion) {
    const char *api = motion ? "NET_DVR_FindFileByEvent" : "NET_DVR_FindFile_V30";
    LONG handle = -1;
    if (motion) {
        if (channel < 1 || channel > MAX_CHANNUM_V30)
            return "{\"state\":\"unsupported\",\"sdk_error\":4,\"complete\":false,\"intervals\":null}";
        NET_DVR_SEARCH_EVENT_PARAM request{};
        request.wMajorType = 0; request.wMinorType = 0xffff;
        request.struStartTime = begin; request.struEndTime = end;
        request.byLockType = 0xff; request.byValue = 0;
        request.uSeniorParam.struMotionParam.byMotDetChanNo[channel - 1] = 1;
        handle = NET_DVR_FindFileByEvent(user, &request);
    } else {
        NET_DVR_FILECOND request{};
        request.lChannel = channel; request.dwFileType = request.dwIsLocked = 0xff;
        request.struStartTime = begin; request.struStopTime = end;
        handle = NET_DVR_FindFile_V30(user, &request);
    }
    if (handle < 0) {
        const auto error = NET_DVR_GetLastError();
        return "{\"state\":" + quote(error == NET_DVR_NOSUPPORT ? "unsupported" : "error") +
            ",\"source\":" + quote(api) + ",\"sdk_error\":" + std::to_string(error) +
            ",\"complete\":false,\"intervals\":null}";
    }
    std::ostringstream intervals;
    unsigned count = 0; bool complete = false; DWORD error = 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (!stopping && count < 256 && std::chrono::steady_clock::now() < deadline) {
        NET_DVR_FINDDATA_V30 recording{}; NET_DVR_SEARCH_EVENT_RET event_result{};
        const LONG status = motion ? NET_DVR_FindNextEvent(handle, &event_result) :
            NET_DVR_FindNextFile_V30(handle, &recording);
        if (status == NET_DVR_ISFINDING) { std::this_thread::sleep_for(std::chrono::milliseconds(30)); continue; }
        if (status == NET_DVR_FILE_NOFIND || status == NET_DVR_NOMOREFILE) { complete = true; break; }
        if (status != NET_DVR_FILE_SUCCESS) { error = NET_DVR_GetLastError(); if (!error) error = 23; break; }
        if (count++) intervals << ',';
        intervals << "{\"start\":" << quote(history_time(motion ? event_result.struStartTime : recording.struStartTime))
            << ",\"end\":" << quote(history_time(motion ? event_result.struEndTime : recording.struStopTime))
            << ",\"recording_type\":" << (motion ? 1 : static_cast<unsigned>(recording.byFileType)) << "}";
    }
    const bool closed = NET_DVR_FindClose_V30(handle);
    if (!closed && !error) error = NET_DVR_GetLastError();
    std::ostringstream result;
    result << "{\"state\":" << quote(error ? "error" : "ready") << ",\"source\":" << quote(api)
        << ",\"sdk_error\":" << error << ",\"complete\":" << (complete && !error ? "true" : "false")
        << ",\"intervals\":" << (error ? "null" : "[" + intervals.str() + "]") << "}";
    return result.str();
}

static void history_query(LONG user, const std::string &id, int channel,
                          NET_DVR_TIME begin, NET_DVR_TIME end) {
    NET_DVR_TIME now{}; DWORD returned = 0;
    const bool clock_ok = NET_DVR_GetDVRConfig(user, NET_DVR_GET_TIMECFG, -1, &now, sizeof(now), &returned)
        && returned >= sizeof(now);
    const auto recordings = history_search(user, channel, begin, end, false);
    const auto motion = history_search(user, channel, begin, end, true);
    event("{\"type\":\"timeline\",\"id\":" + quote(id) + ",\"recorder_now\":" +
        (clock_ok ? quote(history_time(now)) : "null") + ",\"recordings\":" + recordings +
        ",\"motion\":" + motion + "}");
}
