import unittest

from mrsiprep.utils.debug import Debug, collect_timings, set_timing_sink


class DebugStepTimingTests(unittest.TestCase):
    def tearDown(self):
        set_timing_sink(False)

    def test_no_timing_recorded_without_sink(self):
        debug = Debug(verbose=0)
        with debug.step("Untracked step"):
            pass
        self.assertEqual(collect_timings(), [])

    def test_records_step_duration_when_sink_armed(self):
        set_timing_sink(True)
        debug = Debug(verbose=0)
        with debug.step("Step A"):
            pass
        with debug.step("Step B"):
            pass
        timings = collect_timings()
        self.assertEqual([entry["step"] for entry in timings], ["Step A", "Step B"])
        for entry in timings:
            self.assertGreaterEqual(entry["seconds"], 0.0)

    def test_records_duration_even_when_step_raises(self):
        set_timing_sink(True)
        debug = Debug(verbose=0)
        with self.assertRaises(ValueError):
            with debug.step("Failing step"):
                raise ValueError("boom")
        timings = collect_timings()
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["step"], "Failing step")

    def test_records_regardless_of_verbosity(self):
        """Timing must be captured even at verbose=0, where step() normally
        skips all console/logbook output entirely -- the Runtime report tab
        needs this independent of what gets printed."""
        set_timing_sink(True)
        debug = Debug(verbose=0)
        with debug.step("Silent step"):
            pass
        self.assertEqual(len(collect_timings()), 1)

    def test_clearing_sink_resets_accumulator(self):
        set_timing_sink(True)
        debug = Debug(verbose=0)
        with debug.step("Step A"):
            pass
        set_timing_sink(False)
        self.assertEqual(collect_timings(), [])
        set_timing_sink(True)
        self.assertEqual(collect_timings(), [], "a freshly armed sink should start empty")


if __name__ == "__main__":
    unittest.main()
