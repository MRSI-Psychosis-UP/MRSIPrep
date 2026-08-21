import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.utils.runtime_metrics import read_runtime_metrics, write_runtime_metrics
from mrsiprep.workflows.registration import RegistrationResult, run_registration_workflow

MODULE = "mrsiprep.workflows.registration"


def _config(**overrides):
    base = dict(
        output_spaces=["MNI152NLin2009cAsym"],
        parcellation_mode="synthseg",
        transform="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class RunRegistrationWorkflowTests(unittest.TestCase):
    def _patches(self):
        return (
            patch(f"{MODULE}.run_mrsi_to_t1", return_value="MRSI2T1"),
            patch(f"{MODULE}.run_t1_to_mni", return_value="T12MNI"),
            patch(f"{MODULE}.compose_longitudinal_t1_to_mni", return_value="COMPOSED"),
        )

    def test_mrsi_to_t1_always_runs_and_masks_are_forwarded(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p as mrsi_mock, mni_p, comp_p:
            result = run_registration_workflow(
                _config(output_spaces=["T1w"]), "S001", "V1", "REF", "T1",
                registration_mask="FIXED", mrsi_mask="MOVING",
            )

        mrsi_mock.assert_called_once()
        self.assertEqual(mrsi_mock.call_args.kwargs["fixed_mask"], "FIXED")
        self.assertEqual(mrsi_mock.call_args.kwargs["moving_mask"], "MOVING")
        self.assertEqual(result.mrsi_to_t1, "MRSI2T1")

    def test_mni_stage_is_skipped_when_nothing_requests_it(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p:
            result = run_registration_workflow(_config(output_spaces=["T1w"]), "S001", "V1", "REF", "T1")

        mni_mock.assert_not_called()
        self.assertIsNone(result.t1_to_mni)

    def test_mni_output_space_triggers_the_mni_stage(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p:
            result = run_registration_workflow(_config(), "S001", "V1", "REF", "T1")

        mni_mock.assert_called_once()
        self.assertEqual(result.t1_to_mni, "T12MNI")

    def test_atlas_parcellation_triggers_the_mni_stage_even_without_mni_output(self):
        # Atlas parcellation warps an MNI-space atlas back, so it needs the
        # T1w->MNI transform regardless of which spaces are written out.
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p:
            result = run_registration_workflow(
                _config(output_spaces=["T1w"], parcellation_mode="atlas"), "S001", "V1", "REF", "T1"
            )

        mni_mock.assert_called_once()
        self.assertEqual(result.t1_to_mni, "T12MNI")

    def test_legacy_transform_string_triggers_the_mni_stage(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p:
            run_registration_workflow(
                _config(output_spaces=["T1w"], transform="mni-nonlinear"), "S001", "V1", "REF", "T1"
            )

        mni_mock.assert_called_once()

    def test_chimera_parcellation_alone_does_not_trigger_the_mni_stage(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p:
            run_registration_workflow(
                _config(output_spaces=["T1w"], parcellation_mode="chimera"), "S001", "V1", "REF", "T1"
            )

        mni_mock.assert_not_called()

    def test_subject_template_composes_instead_of_registering_directly(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p as comp_mock:
            result = run_registration_workflow(
                _config(), "S001", "V1", "REF", "T1", subject_template="TEMPLATE"
            )

        comp_mock.assert_called_once()
        mni_mock.assert_not_called()
        self.assertEqual(result.t1_to_mni, "COMPOSED")
        self.assertEqual(comp_mock.call_args.args[3], "TEMPLATE")

    def test_sessionless_recording_registers_directly_even_with_a_template(self):
        # Composition is per-session; without a session there is nothing to
        # compose through, so fall back to a direct registration.
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p as mni_mock, comp_p as comp_mock:
            result = run_registration_workflow(
                _config(), "S001", None, "REF", "T1", subject_template="TEMPLATE"
            )

        comp_mock.assert_not_called()
        mni_mock.assert_called_once()
        self.assertEqual(result.t1_to_mni, "T12MNI")

    def test_returns_a_registration_result(self):
        mrsi_p, mni_p, comp_p = self._patches()
        with mrsi_p, mni_p, comp_p:
            result = run_registration_workflow(_config(), "S001", "V1", "REF", "T1")

        self.assertIsInstance(result, RegistrationResult)


class WriteRuntimeMetricsTests(unittest.TestCase):
    def _config(self, root, **overrides):
        base = dict(derivative_dir=root / "derivatives", nproc=2, nthreads=8)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_writes_json_with_the_expected_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            steps = [{"step": "Registration", "seconds": 12.5}]

            out = write_runtime_metrics(self._config(root), "S001", "V1", steps, 30.0, "completed")

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["total_seconds"], 30.0)
            self.assertEqual(payload["steps"], steps)
            self.assertEqual(payload["nproc"], 2)
            self.assertEqual(payload["nthreads"], 8)
            self.assertIn("hostname", payload)
            self.assertIn("generated_at", payload)

    def test_parent_directories_are_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = write_runtime_metrics(self._config(Path(tmpdir)), "S001", "V1", [], 0.0, "failed")
            self.assertTrue(out.exists())

    def test_missing_nproc_nthreads_are_recorded_as_null(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = SimpleNamespace(derivative_dir=root / "derivatives")

            out = write_runtime_metrics(config, "S001", "V1", [], 1.0, "completed")

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertIsNone(payload["nproc"])
            self.assertIsNone(payload["nthreads"])

    def test_sessionless_recording_is_supported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = write_runtime_metrics(self._config(Path(tmpdir)), "S001", None, [], 1.0, "completed")
            self.assertTrue(out.exists())

    def test_rewriting_replaces_the_previous_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._config(root)

            write_runtime_metrics(config, "S001", "V1", [], 1.0, "failed")
            out = write_runtime_metrics(config, "S001", "V1", [], 2.0, "completed")

            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["total_seconds"], 2.0)


class ReadRuntimeMetricsTests(unittest.TestCase):
    def _config(self, root):
        return SimpleNamespace(derivative_dir=root / "derivatives", nproc=1, nthreads=1)

    def test_round_trips_what_write_produced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._config(root)
            write_runtime_metrics(config, "S001", "V1", [{"step": "A", "seconds": 1.0}], 5.0, "completed")

            payload = read_runtime_metrics(config, "S001", "V1")

            self.assertEqual(payload["total_seconds"], 5.0)
            self.assertEqual(payload["steps"], [{"step": "A", "seconds": 1.0}])

    def test_absent_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(read_runtime_metrics(self._config(Path(tmpdir)), "S001", "V1"))

    def test_corrupt_json_returns_none_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = self._config(root)
            write_runtime_metrics(config, "S001", "V1", [], 1.0, "completed")

            from mrsiprep.io.naming import runtime_metrics_derivative

            runtime_metrics_derivative(config.derivative_dir, "S001", "V1").write_text(
                "{not valid json", encoding="utf-8"
            )

            self.assertIsNone(read_runtime_metrics(config, "S001", "V1"))


if __name__ == "__main__":
    unittest.main()
