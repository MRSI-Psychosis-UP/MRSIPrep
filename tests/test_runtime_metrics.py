import tempfile
import unittest
from pathlib import Path

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.utils.runtime_metrics import read_runtime_metrics, write_runtime_metrics


def _make_config(tmp_path: Path, **overrides) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
        metabolites=["CrPCr"],
        ref_met="CrPCr",
        **overrides,
    )


class WriteReadRuntimeMetricsTests(unittest.TestCase):
    def test_round_trips_step_timings_and_context(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path, nproc=2, nthreads=8)
            timings = [{"step": "Tissue segmentation", "seconds": 12.3}, {"step": "Registration", "seconds": 45.6}]
            out = write_runtime_metrics(config, "S001", "V1", timings, total_seconds=57.9, status="success")
            self.assertTrue(out.exists())

            payload = read_runtime_metrics(config, "S001", "V1")
            self.assertIsNotNone(payload)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["total_seconds"], 57.9)
            self.assertEqual(payload["steps"], timings)
            self.assertEqual(payload["nproc"], 2)
            self.assertEqual(payload["nthreads"], 8)

    def test_read_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            self.assertIsNone(read_runtime_metrics(config, "S001", "V1"))

    def test_read_returns_none_on_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            from mrsiprep.io.naming import runtime_metrics_derivative

            path = runtime_metrics_derivative(config.derivative_dir, "S001", "V1")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(read_runtime_metrics(config, "S001", "V1"))


if __name__ == "__main__":
    unittest.main()
