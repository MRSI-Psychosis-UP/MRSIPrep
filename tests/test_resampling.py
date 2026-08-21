import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.mrsi.resampling import resample_ref_met_to_t1w, transform_mrsi_maps


def _cfg(**over):
    d = tempfile.mkdtemp()
    base = dict(bids_dir=d, output_dir=str(Path(d) / "out"), analysis_level="participant", metabolites=["CrPCr"], ref_met="CrPCr")
    base.update(over)
    return MRSIPrepConfig(**base)


class TransformMrsiMapsScopeTests(unittest.TestCase):
    """T1w-space resampling is opt-in (--output-mrsi-t1w); MNI-space stays on
    whenever MNI is in --output-spaces and a t1_to_mni transform exists."""

    def _run(self, config, t1_to_mni):
        with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=lambda fixed, moving, transforms, out, **kw: out), patch(
            "mrsiprep.mrsi.resampling.datasets.load_mni152_template", return_value=object()
        ), patch("mrsiprep.mrsi.resampling.resolve_mni_resolution", return_value=1):
            return transform_mrsi_maps(
                config,
                "S001",
                "V1",
                {"CrPCr": Path("/tmp/crpcr.nii.gz")},
                mrsi_to_t1=[Path("/tmp/xfm.h5")],
                t1_to_mni=t1_to_mni,
                t1_reference=Path("/tmp/t1.nii.gz"),
            )

    def test_default_config_produces_only_mni_no_t1w(self):
        outputs = self._run(_cfg(), t1_to_mni=[Path("/tmp/mni.h5")])
        self.assertNotIn("T1w", outputs)
        self.assertIn("MNI152NLin2009cAsym", outputs)

    def test_output_mrsi_t1w_flag_adds_t1w_space(self):
        outputs = self._run(_cfg(output_mrsi_t1w=True), t1_to_mni=[Path("/tmp/mni.h5")])
        self.assertIn("T1w", outputs)
        self.assertIn("MNI152NLin2009cAsym", outputs)

    def test_no_mni_transform_means_no_mni_output(self):
        outputs = self._run(_cfg(), t1_to_mni=None)
        self.assertNotIn("MNI152NLin2009cAsym", outputs)
        self.assertNotIn("T1w", outputs)


class ResampleRefMetToT1wTests(unittest.TestCase):
    """The report's minimal T1w reference map lives under --work-dir, not the
    permanent BIDS derivatives tree."""

    def test_written_under_work_dir(self):
        config = _cfg()
        with patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=lambda fixed, moving, transforms, out, **kw: out):
            out = resample_ref_met_to_t1w(config, "S001", "V1", Path("/tmp/crpcr.nii.gz"), [Path("/tmp/xfm.h5")], Path("/tmp/t1.nii.gz"))
        self.assertTrue(str(out).startswith(str(config.work_dir)))
        self.assertNotIn(str(config.derivative_dir), str(out))


if __name__ == "__main__":
    unittest.main()
