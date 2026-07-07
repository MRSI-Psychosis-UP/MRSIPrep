import unittest

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.io.validators import validate_recording
from mrsiprep.workflows.participant import validate_participant_inputs


def _write_quality_maps(mrsi_dir, img, subject, session, metabolites, save):
    for met in metabolites:
        save(img, mrsi_dir / f"sub-{subject}_ses-{session}_space-orig_met-{met}_desc-crlb_mrsi.nii.gz")
    save(img, mrsi_dir / f"sub-{subject}_ses-{session}_space-orig_desc-snr_mrsi.nii.gz")
    save(img, mrsi_dir / f"sub-{subject}_ses-{session}_space-orig_desc-fwhm_mrsi.nii.gz")


class BIDSInputTests(unittest.TestCase):
    def test_brain_csf_requires_p3(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            import nibabel as nib
            import numpy as np

            tmp_path = Path(td)
            bids = tmp_path / "bids"
            anat = bids / "sub-S001" / "ses-V1" / "anat"
            mrsi = bids / "derivatives" / "mrsi-orig" / "sub-S001" / "ses-V1"
            skull = bids / "derivatives" / "skullstrip" / "sub-S001" / "ses-V1"
            anat.mkdir(parents=True)
            mrsi.mkdir(parents=True)
            skull.mkdir(parents=True)
            img = nib.Nifti1Image(np.ones((2, 2, 2), dtype="float32"), np.eye(4))
            nib.save(img, skull / "sub-S001_ses-V1_desc-brain_T1w.nii.gz")
            metabolites = ["CrPCr", "GluGln", "GPCPCh", "NAANAAG", "Ins"]
            for met in metabolites:
                nib.save(img, mrsi / f"sub-S001_ses-V1_space-orig_met-{met}_desc-signal_mrsi.nii.gz")
            _write_quality_maps(mrsi, img, "S001", "V1", metabolites, nib.save)
            cfg = MRSIPrepConfig(
                bids,
                tmp_path / "derivatives",
                "participant",
                participant_label=["S001"],
                session_label=["V1"],
                processing_mode="parc-con",
                tissue_backend="existing",
            )
            with self.assertRaisesRegex(Exception, "p3"):
                validate_recording(cfg, "S001", "V1")

            cfg_synthseg_fast = MRSIPrepConfig(
                bids,
                tmp_path / "derivatives",
                "participant",
                participant_label=["S001"],
                session_label=["V1"],
                processing_mode="parc-con",
                tissue_backend="synthseg-fast",
            )
            validate_recording(cfg_synthseg_fast, "S001", "V1")

    def test_synthseg_fast_accepts_raw_t1_reference(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            import nibabel as nib
            import numpy as np

            tmp_path = Path(td)
            bids = tmp_path / "bids"
            anat = bids / "sub-S001" / "ses-V1" / "anat"
            mrsi = bids / "derivatives" / "mrsi-orig" / "sub-S001" / "ses-V1"
            anat.mkdir(parents=True)
            mrsi.mkdir(parents=True)
            img = nib.Nifti1Image(np.ones((2, 2, 2), dtype="float32"), np.eye(4))
            raw_t1 = anat / "sub-S001_ses-V1_acq-mprage_run-01_T1w.nii.gz"
            nib.save(img, raw_t1)
            metabolites = ["CrPCr", "GluGln", "GPCPCh", "NAANAAG", "Ins"]
            for met in metabolites:
                nib.save(img, mrsi / f"sub-S001_ses-V1_space-orig_met-{met}_desc-signal_mrsi.nii.gz")
            _write_quality_maps(mrsi, img, "S001", "V1", metabolites, nib.save)

            cfg = MRSIPrepConfig(
                bids,
                tmp_path / "derivatives",
                "participant",
                participant_label=["S001"],
                session_label=["V1"],
                tissue_backend="synthseg-fast",
            )

            t1, _ = validate_recording(cfg, "S001", "V1")
            self.assertEqual(t1, raw_t1)

    def test_validate_participant_inputs_reports_each_recording(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            import nibabel as nib
            import numpy as np

            tmp_path = Path(td)
            bids = tmp_path / "bids"
            img = nib.Nifti1Image(np.ones((2, 2, 2), dtype="float32"), np.eye(4))
            for ses in ["V1", "V2"]:
                anat = bids / "sub-S001" / f"ses-{ses}" / "anat"
                mrsi = bids / "derivatives" / "mrsi-orig" / "sub-S001" / f"ses-{ses}"
                anat.mkdir(parents=True)
                mrsi.mkdir(parents=True)
                nib.save(img, anat / f"sub-S001_ses-{ses}_acq-mprage_run-01_T1w.nii.gz")
                metabolites = ["CrPCr", "GluGln", "GPCPCh", "NAANAAG", "Ins"]
                if ses == "V2":
                    metabolites.remove("Ins")
                for met in metabolites:
                    nib.save(img, mrsi / f"sub-S001_ses-{ses}_space-orig_met-{met}_desc-signal_mrsi.nii.gz")
                _write_quality_maps(mrsi, img, "S001", ses, metabolites, nib.save)

            cfg = MRSIPrepConfig(
                bids,
                tmp_path / "derivatives",
                "participant",
                participant_label=["S001"],
                session_label=["V1", "V2"],
                tissue_backend="synthseg-fast",
            )

            statuses = validate_participant_inputs(cfg)

            self.assertEqual([status.status for status in statuses], ["success", "failed"])
            self.assertIn("Ins", statuses[1].error)
