"""Exercise the production C++ buffer without recorder, SDK, or network."""
import subprocess
import unittest


class NativePlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["g++", "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror",
                        "-I/probe", "/native/playback_buffer_test.cpp", "-o", "/tmp/playback-buffer-test"],
                       check=True, capture_output=True, text=True, timeout=30)

    def check_scenario(self, name):
        subprocess.run(["/tmp/playback-buffer-test", name], check=True,
                       capture_output=True, text=True, timeout=10)

    def test_decoder_refusal_preserves_order_and_capacity(self): self.check_scenario("refusal")
    def test_stop_wakes_blocked_callback(self): self.check_scenario("cancel")
    def test_fast_producer_slow_decoder_is_bounded_and_lossless(self): self.check_scenario("burst")
