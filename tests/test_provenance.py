import tempfile
import unittest
from pathlib import Path

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.utils.provenance import pipeline_trace


def _cfg(**over):
    d = tempfile.mkdtemp()
    base = dict(bids_dir=d, output_dir=str(Path(d) / "out"), analysis_level="participant", metabolites=["CrPCr"], ref_met="CrPCr")
    base.update(over)
    return MRSIPrepConfig(**base)


class PipelineTraceTests(unittest.TestCase):
    def _status(self, trace, step):
        return next(e for e in trace if e["step"] == step)["status"]

    def test_mni_norm_skips_parc_con_only_steps(self):
        trace = pipeline_trace(_cfg(processing_mode="mni-norm"))
        for step in ("Parcellation (chimera/mni atlas)", "Metprofiles export"):
            self.assertEqual(self._status(trace, step), "SKIPPED")
        for step in (
            "Tissue segmentation",
            "Anatomical preparation",
            "MRSI preprocessing",
            "Tissue probability maps in MRSI space",
            "Partial volume correction",
            "Reports",
        ):
            self.assertEqual(self._status(trace, step), "RAN")

    def test_parc_con_runs_gated_steps_by_default(self):
        trace = pipeline_trace(_cfg(processing_mode="parc-con"))
        for step in ("Tissue probability maps in MRSI space", "Partial volume correction", "Parcellation (chimera/mni atlas)", "Metprofiles export"):
            self.assertEqual(self._status(trace, step), "RAN")

    def test_no_pvc_flag_skips_only_pvc(self):
        for mode in ("parc-con", "mni-norm"):
            trace = pipeline_trace(_cfg(processing_mode=mode, no_pvc=True))
            self.assertEqual(self._status(trace, "Partial volume correction"), "SKIPPED", f"mode={mode}")
        trace = pipeline_trace(_cfg(processing_mode="parc-con", no_pvc=True))
        self.assertEqual(self._status(trace, "Parcellation (chimera/mni atlas)"), "RAN")

    def test_connectivity_gated_by_write_connectivity_flag(self):
        self.assertEqual(self._status(pipeline_trace(_cfg(processing_mode="parc-con")), "Connectivity"), "SKIPPED")
        self.assertEqual(self._status(pipeline_trace(_cfg(processing_mode="parc-con", write_connectivity=True)), "Connectivity"), "RAN")

    def test_every_entry_has_a_reason_iff_skipped(self):
        for trace in (pipeline_trace(_cfg(processing_mode="mni-norm")), pipeline_trace(_cfg(processing_mode="parc-con"))):
            for entry in trace:
                if entry["status"] == "SKIPPED":
                    self.assertTrue(entry["reason"])
                else:
                    self.assertEqual(entry["reason"], "")


if __name__ == "__main__":
    unittest.main()
