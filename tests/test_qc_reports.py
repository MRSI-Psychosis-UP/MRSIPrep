import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.reports.connectivity_overview import write_connectivity_qc_report
from mrsiprep.reports.mrsi_preproc import write_mrsi_preproc_qc_report
from mrsiprep.reports.parcellation_overview import write_parcellation_qc_report
from mrsiprep.reports.qc_combine import combine_qc_reports
from mrsiprep.reports.registration_overview import write_registration_overview_report
from mrsiprep.reports.tissue import write_tissue_qc_report


def _make_config(tmp_path: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
    )


def _save_volume(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), np.eye(4)), path)
    return path


class TissueQCReportTests(unittest.TestCase):
    def test_writes_html_with_labels_and_probsegs(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            dseg = _save_volume(tmp_path / "dseg.nii.gz", np.random.randint(0, 3, (8, 8, 8)))
            probsegs = {
                "GM": _save_volume(tmp_path / "gm.nii.gz", np.random.rand(8, 8, 8)),
                "WM": _save_volume(tmp_path / "wm.nii.gz", np.random.rand(8, 8, 8)),
            }
            out = write_tissue_qc_report(config, "S001", "V1", raw_t1, dseg, probsegs)
            self.assertTrue(out.exists())
            html = out.read_text()
            self.assertIn("Tissue label outlines", html)
            self.assertIn("GM", html)

    def test_handles_missing_dseg_and_probsegs_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            out = write_tissue_qc_report(config, "S001", "V1", raw_t1, None, None)
            self.assertTrue(out.exists())
            self.assertIn("No tissue label image available", out.read_text())


class MRSIPreprocQCReportTests(unittest.TestCase):
    def test_writes_before_after_pairs_per_metabolite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.rand(8, 8, 8)
            preproc = raw.copy()
            preproc[2:4, 2:4, 2:4] = 0.0
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            out = write_mrsi_preproc_qc_report(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertTrue(out.exists())
            html = out.read_text()
            self.assertIn("CrPCr", html)
            self.assertIn("centroid", html)

    def test_handles_mismatched_trailing_singleton_dimension(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.rand(44, 44, 25, 1)
            preproc = np.squeeze(raw.copy())
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            out = write_mrsi_preproc_qc_report(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertTrue(out.exists())

    def test_handles_no_repaired_voxels(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            same = np.random.rand(8, 8, 8)
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", same)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", same.copy())}
            out = write_mrsi_preproc_qc_report(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertIn("No voxels required repair", out.read_text())


class RegistrationOverviewReportTests(unittest.TestCase):
    def test_writes_t1w_section_and_skips_mni_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            t1_ref = _save_volume(tmp_path / "ref_t1.nii.gz", np.random.rand(8, 8, 8))
            out = write_registration_overview_report(config, "S001", "V1", raw_t1, t1_ref, None)
            html = out.read_text()
            self.assertIn("T1w-space alignment", html)
            self.assertIn("not available for this configuration", html)

    def test_handles_missing_t1_map(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            out = write_registration_overview_report(config, "S001", "V1", raw_t1, None, None)
            self.assertIn("No T1w-space reference metabolite map available", out.read_text())

    def test_computes_t1w_alignment_on_demand_when_not_already_transformed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            orig_ref = _save_volume(tmp_path / "orig_ref.nii.gz", np.random.rand(8, 8, 8))
            fake_transform = tmp_path / "fake.h5"
            fake_transform.write_bytes(b"not-a-real-transform")

            def _fake_apply(fixed, moving, transforms, out_path, interpolation="linear", threads=None):
                out_path = Path(out_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                nib.save(nib.load(str(moving)), out_path)
                return out_path

            with mock.patch("mrsiprep.registration.transforms.apply_image_transform", side_effect=_fake_apply):
                out = write_registration_overview_report(
                    config,
                    "S001",
                    "V1",
                    raw_t1,
                    None,
                    None,
                    orig_ref_map_path=orig_ref,
                    mrsi_to_t1_transforms=[fake_transform],
                )
            html = out.read_text()
            self.assertIn("T1w-space alignment", html)
            self.assertNotIn("No T1w-space reference metabolite map available", html)


class ParcellationQCReportTests(unittest.TestCase):
    def test_writes_outline_overlay(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            atlas_t1 = _save_volume(tmp_path / "atlas_t1.nii.gz", np.random.randint(0, 4, (8, 8, 8)))
            labels_path = tmp_path / "labels.tsv"
            pd.DataFrame({"parcel_id": [1, 2, 3], "parcel_name": ["a", "b", "c"]}).to_csv(labels_path, sep="\t", index=False)
            out = write_parcellation_qc_report(config, "S001", "V1", raw_t1, atlas_t1, labels_path)
            html = out.read_text()
            self.assertIn("Parcellation outlines", html)
            self.assertIn("3 regions", html)

    def test_handles_missing_atlas(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            out = write_parcellation_qc_report(config, "S001", "V1", raw_t1, None, None)
            self.assertIn("Atlas not available in T1w space", out.read_text())


class ConnectivityQCReportTests(unittest.TestCase):
    def test_writes_heatmap_when_matrix_present(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            matrix = pd.DataFrame(np.eye(3), index=["a", "b", "c"], columns=["a", "b", "c"])
            matrix_path = tmp_path / "matrix.tsv"
            matrix.to_csv(matrix_path, sep="\t")
            out = write_connectivity_qc_report(config, "S001", "V1", matrix_path)
            html = out.read_text()
            self.assertIn("Connectivity matrix", html)
            self.assertIn("spearman", html)

    def test_handles_missing_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            out = write_connectivity_qc_report(config, "S001", "V1", None)
            self.assertIn("not requested", out.read_text())


class CombineQCReportsTests(unittest.TestCase):
    def test_combines_in_chronological_order_and_deletes_originals(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            write_tissue_qc_report(config, "S001", "V1", raw_t1, None, None)
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", np.random.rand(8, 8, 8))}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", np.random.rand(8, 8, 8))}
            write_mrsi_preproc_qc_report(config, "S001", "V1", raw_maps, preproc_maps)
            write_connectivity_qc_report(config, "S001", "V1", None)

            step_files = [
                qc_report_derivative(config.derivative_dir, "S001", "V1", step)
                for step in ("tissue", "mrsi-preproc", "registration", "parcellation", "connectivity")
            ]
            self.assertTrue(step_files[0].exists())
            self.assertTrue(step_files[1].exists())
            self.assertFalse(step_files[2].exists())

            combined = combine_qc_reports(config, "S001", "V1")
            self.assertTrue(combined.exists())
            html = combined.read_text()
            tissue_pos = html.index("Tissue segmentation QC")
            preproc_pos = html.index("MRSI preprocessing QC")
            connectivity_pos = html.index("Connectivity QC")
            self.assertLess(tissue_pos, preproc_pos)
            self.assertLess(preproc_pos, connectivity_pos)

            for step_file in step_files:
                self.assertFalse(step_file.exists())

    def test_returns_none_when_no_step_reports_exist(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            self.assertIsNone(combine_qc_reports(config, "S001", "V1"))


if __name__ == "__main__":
    unittest.main()
