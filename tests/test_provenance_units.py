import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from mrsiprep.utils.provenance import (
    NumpyEncoder,
    check_external_software,
    pipeline_trace,
    required_external_tools,
    software_versions,
    write_provenance,
)


class NumpyEncoderTests(unittest.TestCase):
    def test_encodes_ndarray_as_list(self):
        self.assertEqual(json.loads(json.dumps({"a": np.array([1, 2, 3])}, cls=NumpyEncoder)), {"a": [1, 2, 3]})

    def test_encodes_numpy_scalar_as_python_item(self):
        encoded = json.dumps({"a": np.float32(1.5)}, cls=NumpyEncoder)
        self.assertEqual(json.loads(encoded), {"a": 1.5})

    def test_encodes_path_as_string(self):
        self.assertEqual(json.loads(json.dumps({"a": Path("/tmp/x")}, cls=NumpyEncoder)), {"a": "/tmp/x"})

    def test_unsupported_type_still_raises(self):
        with self.assertRaises(TypeError):
            json.dumps({"a": object()}, cls=NumpyEncoder)


def _cfg(**overrides):
    base = dict(
        registration_backend="ants",
        processing_mode="parc-con",
        tissue_backend="synthseg-fast",
        no_pvc=False,
        parcellation_mode="chimera",
        longitudinal=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class RequiredExternalToolsTests(unittest.TestCase):
    def test_none_config_returns_full_default_tool_list(self):
        tools = required_external_tools(None)
        self.assertIn("fast", tools)
        self.assertIn("petpvc", tools)
        self.assertIn("chimera", tools)
        self.assertIn("recon-all", tools)
        self.assertNotIn("flirt", tools)

    def test_fsl_backend_adds_flirt_and_convert_xfm(self):
        tools = required_external_tools(_cfg(registration_backend="fsl"))
        self.assertIn("flirt", tools)
        self.assertIn("convert_xfm", tools)

    def test_mni_norm_mode_excludes_full_only_tools(self):
        tools = required_external_tools(_cfg(processing_mode="mni-norm"))
        self.assertNotIn("fast", tools)
        self.assertNotIn("petpvc", tools)
        self.assertNotIn("chimera", tools)
        self.assertNotIn("recon-all", tools)

    def test_no_pvc_excludes_petpvc_but_keeps_other_full_tools(self):
        tools = required_external_tools(_cfg(no_pvc=True))
        self.assertNotIn("petpvc", tools)
        self.assertIn("fast", tools)
        self.assertIn("chimera", tools)

    def test_non_chimera_parcellation_excludes_chimera_and_reconall(self):
        tools = required_external_tools(_cfg(parcellation_mode="mni"))
        self.assertNotIn("chimera", tools)
        self.assertNotIn("recon-all", tools)

    def test_longitudinal_adds_template_construction_tools(self):
        tools = required_external_tools(_cfg(longitudinal=True))
        for tool in ("antsMultivariateTemplateConstruction2.sh", "antsAI", "AverageImages"):
            self.assertIn(tool, tools)

    def test_result_has_no_duplicates(self):
        tools = required_external_tools(_cfg())
        self.assertEqual(len(tools), len(set(tools)))

    def test_non_synthseg_fast_backend_excludes_fast_but_keeps_petpvc(self):
        tools = required_external_tools(_cfg(tissue_backend="existing"))
        self.assertNotIn("fast", tools)
        self.assertIn("petpvc", tools)


class SoftwareVersionsTests(unittest.TestCase):
    def test_maps_each_required_tool_to_which_result(self):
        with patch("mrsiprep.utils.provenance.shutil.which", side_effect=lambda tool: f"/usr/bin/{tool}" if tool == "fast" else None):
            versions = software_versions(_cfg())
        self.assertEqual(versions["fast"], "/usr/bin/fast")
        self.assertIsNone(versions["chimera"])


class CheckExternalSoftwareTests(unittest.TestCase):
    def _debug(self):
        debug = MagicMock()
        debug.console = MagicMock()
        return debug

    def test_returns_true_and_reports_success_when_all_available(self):
        debug = self._debug()
        with patch("mrsiprep.utils.provenance.software_versions", return_value={"fast": "/usr/bin/fast"}):
            result = check_external_software(debug, _cfg())
        self.assertTrue(result)
        debug.success.assert_called_once()
        debug.failure.assert_not_called()

    def test_returns_false_and_reports_failure_when_something_missing(self):
        debug = self._debug()
        with patch("mrsiprep.utils.provenance.software_versions", return_value={"fast": None, "chimera": "/usr/bin/chimera"}):
            result = check_external_software(debug, _cfg())
        self.assertFalse(result)
        debug.failure.assert_called_once()
        debug.success.assert_not_called()


class PipelineTraceTests(unittest.TestCase):
    def _status(self, trace, step):
        return next(e for e in trace if e["step"] == step)["status"]

    def _cfg(self, **overrides):
        base = dict(processing_mode="parc-con", no_pvc=False, t1_correction="none", write_connectivity=False)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_mni_norm_runs_tissue_probmaps_and_pvc_but_skips_parc_con_only_steps(self):
        trace = pipeline_trace(self._cfg(processing_mode="mni-norm"))
        for step in ("Parcellation (chimera/mni atlas)", "Metprofiles export"):
            self.assertEqual(self._status(trace, step), "SKIPPED")
        for step in ("Tissue probability maps in MRSI space", "Partial volume correction"):
            self.assertEqual(self._status(trace, step), "RAN")

    def test_parc_con_runs_all_gated_steps_by_default(self):
        trace = pipeline_trace(self._cfg(processing_mode="parc-con"))
        for step in ("Tissue probability maps in MRSI space", "Partial volume correction", "Parcellation (chimera/mni atlas)", "Metprofiles export"):
            self.assertEqual(self._status(trace, step), "RAN")

    def test_no_pvc_skips_pvc_under_both_eligible_modes(self):
        for mode in ("parc-con", "mni-norm"):
            trace = pipeline_trace(self._cfg(processing_mode=mode, no_pvc=True))
            self.assertEqual(self._status(trace, "Partial volume correction"), "SKIPPED")

    def test_t1_correction_gated_on_literature_setting(self):
        self.assertEqual(self._status(pipeline_trace(self._cfg(t1_correction="none")), "T1 saturation correction"), "SKIPPED")
        self.assertEqual(self._status(pipeline_trace(self._cfg(t1_correction="literature")), "T1 saturation correction"), "RAN")

    def test_connectivity_gated_on_write_connectivity_flag(self):
        self.assertEqual(self._status(pipeline_trace(self._cfg(write_connectivity=False)), "Connectivity"), "SKIPPED")
        self.assertEqual(self._status(pipeline_trace(self._cfg(write_connectivity=True)), "Connectivity"), "RAN")

    def test_always_on_steps_never_skipped(self):
        for mode in ("parc-con", "mni-norm"):
            trace = pipeline_trace(self._cfg(processing_mode=mode))
            for step in ("Tissue segmentation", "Anatomical preparation", "MRSI preprocessing", "MRSI-T1w-MNI registration", "Resampling MRSI maps to T1w/MNI space", "SynthSeg parcellation and QC", "Regional metabolite extraction", "Reports"):
                self.assertEqual(self._status(trace, step), "RAN")

    def test_every_entry_has_a_reason_iff_skipped(self):
        for trace in (pipeline_trace(self._cfg(processing_mode="mni-norm")), pipeline_trace(self._cfg(processing_mode="parc-con"))):
            for entry in trace:
                if entry["status"] == "SKIPPED":
                    self.assertTrue(entry["reason"], entry["step"])
                else:
                    self.assertEqual(entry["reason"], "", entry["step"])


class WriteProvenanceTests(unittest.TestCase):
    def test_writes_valid_json_with_expected_top_level_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "nested" / "provenance.json"
            config = SimpleNamespace(processing_mode="parc-con", no_pvc=False, t1_correction="none", write_connectivity=False)
            with patch("mrsiprep.utils.provenance.software_versions", return_value={}):
                result = write_provenance(config, out_path)
            payload = json.loads(out_path.read_text())

        self.assertEqual(result, out_path)
        for key in ("generated_at", "mrsiprep_version", "python", "platform", "config", "software", "pipeline_trace"):
            self.assertIn(key, payload)
        self.assertEqual(payload["config"], {})  # no to_dict() on this config

    def test_uses_config_to_dict_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "provenance.json"
            config = SimpleNamespace(
                processing_mode="parc-con", no_pvc=False, t1_correction="none", write_connectivity=False,
                to_dict=lambda: {"processing_mode": "parc-con"},
            )
            with patch("mrsiprep.utils.provenance.software_versions", return_value={}):
                write_provenance(config, out_path)
            payload = json.loads(out_path.read_text())
        self.assertEqual(payload["config"], {"processing_mode": "parc-con"})

    def test_extra_payload_is_merged_in(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "provenance.json"
            config = SimpleNamespace(processing_mode="parc-con", no_pvc=False, t1_correction="none", write_connectivity=False)
            with patch("mrsiprep.utils.provenance.software_versions", return_value={}):
                write_provenance(config, out_path, extra={"subject": "01", "outputs": {"t1w": "path"}})
            payload = json.loads(out_path.read_text())
        self.assertEqual(payload["subject"], "01")
        self.assertEqual(payload["outputs"], {"t1w": "path"})


if __name__ == "__main__":
    unittest.main()
