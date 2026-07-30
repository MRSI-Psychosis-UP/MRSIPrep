import unittest
from types import SimpleNamespace

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.validators import (
    ValidationError,
    _validate_brain_csf_registration_target,
    _validate_existing_tissue_backend,
    _validate_metabolite_maps_present,
    _validate_quality_maps_present,
)


class ValidateMetaboliteMapsPresentTests(unittest.TestCase):
    def _config(self, metabolites):
        return SimpleNamespace(metabolites=metabolites)

    def test_no_error_when_all_present(self):
        inputs = MRSIInputs(metabolite_maps={"CrPCr": "x", "GluGln": "y"})
        _validate_metabolite_maps_present(self._config(["CrPCr", "GluGln"]), "S001", "V1", inputs)

    def test_raises_listing_missing_metabolites(self):
        inputs = MRSIInputs(metabolite_maps={"CrPCr": "x"})
        with self.assertRaisesRegex(ValidationError, "GluGln"):
            _validate_metabolite_maps_present(self._config(["CrPCr", "GluGln"]), "S001", "V1", inputs)


class ValidateQualityMapsPresentTests(unittest.TestCase):
    def _config(self, quality_metrics, n_metabolites=1):
        return SimpleNamespace(quality_metrics=quality_metrics, metabolites=["CrPCr"] * n_metabolites)

    def test_no_error_when_disabled_metrics_are_missing(self):
        inputs = MRSIInputs()
        _validate_quality_maps_present(self._config([]), "S001", "V1", inputs)

    def test_raises_for_missing_crlb(self):
        inputs = MRSIInputs(crlb_maps={})
        with self.assertRaisesRegex(ValidationError, "crlb"):
            _validate_quality_maps_present(self._config(["crlb"]), "S001", "V1", inputs)

    def test_raises_for_missing_snr(self):
        inputs = MRSIInputs(snr_map=None)
        with self.assertRaisesRegex(ValidationError, "snr"):
            _validate_quality_maps_present(self._config(["snr"]), "S001", "V1", inputs)

    def test_raises_for_missing_linewidth(self):
        inputs = MRSIInputs(linewidth_map=None)
        with self.assertRaisesRegex(ValidationError, "linewidth"):
            _validate_quality_maps_present(self._config(["linewidth"]), "S001", "V1", inputs)

    def test_no_error_when_all_present(self):
        inputs = MRSIInputs(crlb_maps={"CrPCr": "x"}, snr_map="s", linewidth_map="f")
        _validate_quality_maps_present(self._config(["crlb", "snr", "linewidth"]), "S001", "V1", inputs)


class ValidateExistingTissueBackendTests(unittest.TestCase):
    def test_skipped_outside_parc_con_existing(self):
        config = SimpleNamespace(processing_mode="mni-norm", tissue_backend="existing")
        _validate_existing_tissue_backend(config, layout=None, subject="S001", session="V1")

    def test_raises_when_probseg_missing(self):
        config = SimpleNamespace(processing_mode="parc-con", tissue_backend="existing")
        layout = SimpleNamespace(cat12_probseg=lambda subject, session, idx: None)
        with self.assertRaisesRegex(ValidationError, "p1, p2, p3"):
            _validate_existing_tissue_backend(config, layout, "S001", "V1")

    def test_no_error_when_all_probsegs_present(self):
        from pathlib import Path
        import tempfile

        config = SimpleNamespace(processing_mode="parc-con", tissue_backend="existing")
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td) / "p.nii.gz"
            existing.touch()
            layout = SimpleNamespace(cat12_probseg=lambda subject, session, idx: existing)
            _validate_existing_tissue_backend(config, layout, "S001", "V1")


class ValidateBrainCsfRegistrationTargetTests(unittest.TestCase):
    def test_skipped_when_target_is_not_brain_csf(self):
        config = SimpleNamespace(registration_t1_target="brain", tissue_backend="existing")
        _validate_brain_csf_registration_target(config, layout=None, subject="S001", session="V1")

    def test_skipped_when_synthseg_fast_backend(self):
        config = SimpleNamespace(registration_t1_target="brain-csf", tissue_backend="synthseg-fast")
        _validate_brain_csf_registration_target(config, layout=None, subject="S001", session="V1")

    def test_raises_when_p3_missing(self):
        config = SimpleNamespace(registration_t1_target="brain-csf", tissue_backend="existing")
        layout = SimpleNamespace(cat12_probseg=lambda subject, session, idx: None)
        with self.assertRaisesRegex(ValidationError, "p3 CSF"):
            _validate_brain_csf_registration_target(config, layout, "S001", "V1")


if __name__ == "__main__":
    unittest.main()
