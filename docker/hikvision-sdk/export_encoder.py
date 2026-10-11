"""Bounded, cancellable all-frame SDK capture into a verified browser MP4."""
from datetime import timedelta
from fractions import Fraction
import json
import os
from pathlib import Path
import select
import subprocess
import time

from history_timeline import recorder_utc, recorder_wall, utc_text


class ExportFailure(Exception):
    pass


class ExportCancelled(Exception):
    pass


def validate_video(metadata, spec, requested_seconds, count):
    video = next((stream for stream in metadata["streams"] if stream["codec_type"] == "video"), None)
    duration = float(metadata["format"]["duration"])
    if not video or video["codec_name"] != "h264" or (video["width"], video["height"]) != spec[:2]:
        raise ExportFailure("Encoded clip format failed validation.")
    if int(video.get("nb_frames", 0)) != count:
        raise ExportFailure("Encoded clip is missing captured frames.")
    # Match the reported second-level position precision; coverage and timestamp gaps
    # are independently checked before finalizing this constant-rate MP4.
    if abs(duration - requested_seconds) > 1:
        raise ExportFailure(f"Encoded duration {duration:.3f}s does not match the requested {requested_seconds:g}s ({count} frames).")
    return video, duration


class FrameClock:
    """Use recorded OSD time for anchoring, decoder milliseconds for continuity.

    The device clock has second precision; never claim frame-exact wall times.
    Discontinuities fail instead of silently joining gaps or duplicating frames.
    """
    def __init__(self, zone):
        self.zone = zone
        self.anchor = self.first_stamp = self.previous_stamp = None

    def position(self, header):
        if not header.get("position"):
            raise ExportFailure("Recorded frame time unavailable.")
        clock = recorder_utc(header["position"], self.zone) + timedelta(milliseconds=header.get("ms", 0))
        stamp = header["stamp"]
        if type(stamp) is not int or not 0 <= stamp <= 0xffffffff or type(header.get("ms")) is not int or not 0 <= header["ms"] <= 999:
            raise ExportFailure("Invalid decoded frame time.")
        if self.anchor is None:
            self.anchor, self.first_stamp = clock, stamp
        else:
            delta = (stamp - self.previous_stamp) & 0xffffffff
            if not 0 < delta <= max(120, 1500 / header["fps"]):
                raise ExportFailure("Recording has missing or out-of-order frames; choose a continuous range.")
        self.previous_stamp = stamp
        position = self.anchor + timedelta(milliseconds=(stamp - self.first_stamp) & 0xffffffff)
        if abs((position - clock).total_seconds()) > 1:
            raise ExportFailure("Recorded clock changed during capture.")
        return position


class ExportEncoder:
    def __init__(self, worker, zone, max_bytes):
        self.worker, self.zone, self.max_bytes = worker, zone, max_bytes

    def capture(self, job, directory, cancelled, progress):
        identifier = job["id"]
        pipe = directory / "frames.pipe"
        os.mkfifo(pipe, 0o600)
        reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
        encoder = None
        deadline = time.monotonic() + 30 + job["duration_seconds"] * 2
        last_data = time.monotonic()
        buffer = bytearray(); header = None; clock = FrameClock(self.zone)
        first = last = spec = None; count = 0
        partial = directory / "clip.partial.mp4"
        started = False

        def check():
            if cancelled.is_set(): raise ExportCancelled()
            if time.monotonic() > deadline: raise ExportFailure("Export timed out.")
            if partial.exists() and partial.stat().st_size > self.max_bytes:
                raise ExportFailure("Clip exceeds the configured file size limit.")

        def write(data):
            view = memoryview(data)
            while view:
                check()
                if encoder.poll() is not None: raise ExportFailure("Video encoder stopped.")
                if not select.select([], [encoder.stdin], [], .2)[1]: continue
                try: size = os.write(encoder.stdin.fileno(), view)
                except BlockingIOError: continue
                view = view[size:]

        try:
            self.worker.start_export(identifier, job["camera_id"], recorder_wall(job["begin"], self.zone), recorder_wall(job["end"], self.zone))
            started = True
            reached_end = False
            while not reached_end:
                check()
                if not select.select([reader], [], [], .2)[0]:
                    if time.monotonic() - last_data > 20: raise ExportFailure("Recorder stopped delivering export frames.")
                    continue
                chunk = os.read(reader, 65536)
                if not chunk:
                    error = self.worker.export_error(identifier)
                    if error: raise ExportFailure(error)
                    if self.worker.export_complete(identifier): break
                    if time.monotonic() - last_data > 20: raise ExportFailure("No export frames arrived.")
                    time.sleep(.02); continue
                last_data = time.monotonic(); buffer.extend(chunk)
                while True:
                    if header is None:
                        newline = buffer.find(b"\n")
                        if newline < 0:
                            if len(buffer) > 1024: raise ExportFailure("Invalid capture header.")
                            break
                        header = json.loads(buffer[:newline]); del buffer[:newline + 1]
                        w, h, fps, size = (header[key] for key in ("width", "height", "fps", "size"))
                        if any(type(value) is not int for value in (w, h, fps, size)) or not 1 <= fps <= 60 or w <= 0 or h <= 0 or w % 2 or h % 2 or size != w * h * 3 // 2 or size > 4 * 1024 * 1024:
                            raise ExportFailure("Unsupported decoded frame format.")
                    if len(buffer) < header["size"]: break
                    data = bytes(buffer[:header["size"]]); del buffer[:header["size"]]
                    if not header.get("position") and clock.anchor is None:
                        header = None; continue
                    position = clock.position(header)
                    if position >= job["end"]:
                        reached_end = True; break
                    if position >= job["begin"]:
                        current = (w, h, fps)
                        if spec and spec != current: raise ExportFailure("Recording format changed during the clip.")
                        if encoder is None:
                            spec = current; first = position
                            aspect = job["aspect_ratio"]
                            filters = "swapuv" + ("" if aspect == "original" else f",setdar=ratio={aspect.replace(':', '/')}:max=1000")
                            encoder = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", f"{w}x{h}", "-framerate", str(fps), "-i", "pipe:0", "-an", "-vf", filters, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart", str(partial)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            os.set_blocking(encoder.stdin.fileno(), False)
                        write(data); count += 1; last = position
                        progress(min(.95, (position - job["begin"]).total_seconds() / job["duration_seconds"]))
                    header = None
            if not count: raise ExportFailure("No recording found for this range.")
            # Whole-second device precision allows at most one second of edge
            # uncertainty; interior timestamp gaps already fail in FrameClock.
            if (first - job["begin"]).total_seconds() > 1 or (job["end"] - last).total_seconds() > 1:
                raise ExportFailure("Recording does not cover the complete requested range.")
            self.worker.stop_export(identifier); started = False
            encoder.stdin.close()
            try: result = encoder.wait(timeout=20)
            except subprocess.TimeoutExpired: raise ExportFailure("Video finalization timed out.") from None
            check()
            if result or not partial.is_file(): raise ExportFailure("Video encoding failed.")
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(partial)], capture_output=True, check=True, timeout=15)
            metadata = json.loads(probe.stdout)
            video, duration = validate_video(metadata, spec, job["duration_seconds"], count)
            actual_aspect = Fraction(video.get("display_aspect_ratio", "0:1").replace(":", "/"))
            expected_aspect = Fraction(spec[0], spec[1]) if job["aspect_ratio"] == "original" else Fraction(job["aspect_ratio"].replace(":", "/"))
            if abs(float(actual_aspect - expected_aspect)) > .001:
                raise ExportFailure("Encoded clip has incorrect picture proportions.")
            final = directory / "clip.mp4"; partial.replace(final)
            return dict(bytes=final.stat().st_size, actual_duration_seconds=duration, frames=count,
                        actual_from=utc_text(first.replace(microsecond=0)),
                        actual_to=utc_text(min(job["end"], (last + timedelta(seconds=1)).replace(microsecond=0))),
                        position_precision="second", width=spec[0], height=spec[1],
                        display_aspect_ratio=video.get("display_aspect_ratio"))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            raise ExportFailure("Export capture or encoding failed.") from error
        finally:
            if started: self.worker.stop_export(identifier)
            if encoder and encoder.poll() is None:
                encoder.terminate()
                try: encoder.wait(timeout=3)
                except subprocess.TimeoutExpired: encoder.kill(); encoder.wait(timeout=3)
            if encoder and encoder.stdin and not encoder.stdin.closed: encoder.stdin.close()
            os.close(reader); pipe.unlink(missing_ok=True); partial.unlink(missing_ok=True)
            self.worker.forget_export(identifier)
