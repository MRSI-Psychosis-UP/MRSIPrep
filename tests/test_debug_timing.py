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


class StepOutcomeCaptureTests(unittest.TestCase):
    """The Runtime report can only report an outcome the sink recorded."""

    def setUp(self):
        set_timing_sink(True)
        self.addCleanup(set_timing_sink, False)

    def test_successful_step_records_processed(self):
        debug = Debug(verbose=0)
        with debug.step("Tissue segmentation"):
            pass
        entry = collect_timings()[-1]
        self.assertEqual(entry["outcome"], "processed")
        self.assertEqual(entry["step"], "Tissue segmentation")

    def test_raising_step_records_failed_and_still_times_it(self):
        """A failed step keeps its duration: how long the run spent before
        failing is the useful part."""
        debug = Debug(verbose=0)
        with self.assertRaises(ValueError):
            with debug.step("Reports"):
                raise ValueError("boom")
        entry = collect_timings()[-1]
        self.assertEqual(entry["outcome"], "failed")
        self.assertGreaterEqual(entry["seconds"], 0.0)

    def test_the_exception_still_propagates(self):
        debug = Debug(verbose=0)
        with self.assertRaisesRegex(RuntimeError, "propagated"):
            with debug.step("X"):
                raise RuntimeError("propagated")


if __name__ == "__main__":
    unittest.main()
