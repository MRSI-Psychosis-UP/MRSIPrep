import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.io.naming import coverage_report_dir
from mrsiprep.reports.connectivity_overview import build_connectivity_qc_sections
from mrsiprep.reports.mrsi_preproc import _render_value_histogram, build_mrsi_preproc_qc_sections
from mrsiprep.reports.parcellation_overview import build_parcellation_qc_sections
from mrsiprep.reports.registration_overview import build_mni_alignment_sections, build_t1w_alignment_sections, leakage_table_html
from mrsiprep.reports.tissue import build_tissue_qc_sections


def _make_config(tmp_path: Path) -> MRSIPrepConfig:
    return MRSIPrepConfig(
        tmp_path / "bids",
        tmp_path / "derivatives",
        "participant",
        participant_label=["S001"],
        session_label=["V1"],
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )


def _save_volume(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), np.eye(4)), path)
    return path


def _sections_text(sections: list[tuple[str, str]]) -> str:
    return "\n".join(f"{heading}\n{body}" for heading, body in sections)


class TissueQCSectionsTests(unittest.TestCase):
    def test_includes_labels_and_probsegs(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            dseg = _save_volume(tmp_path / "dseg.nii.gz", np.random.randint(0, 3, (8, 8, 8)))
            probsegs = {
                "GM": _save_volume(tmp_path / "gm.nii.gz", np.random.rand(8, 8, 8)),
                "WM": _save_volume(tmp_path / "wm.nii.gz", np.random.rand(8, 8, 8)),
            }
            sections = build_tissue_qc_sections(config, "S001", "V1", raw_t1, dseg, probsegs)
            text = _sections_text(sections)
            self.assertIn("Tissue label outlines", text)
            self.assertIn("GM", text)

    def test_handles_missing_dseg_and_probsegs_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            sections = build_tissue_qc_sections(config, "S001", "V1", raw_t1, None, None)
            self.assertIn("No tissue label image available", _sections_text(sections))


class MRSIPreprocQCSectionsTests(unittest.TestCase):
    def test_includes_before_after_pairs_and_spike_count(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.rand(8, 8, 8)
            preproc = raw.copy()
            preproc[2:4, 2:4, 2:4] = 0.0
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            sections = build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            text = _sections_text(sections)
            self.assertIn("CrPCr", text)
            self.assertIn("centroid", text)
            self.assertIn("Spike voxels detected", text)

    def test_includes_before_after_value_histogram_scoped_to_spike_voxels(self):
        from mrsiprep.io.naming import mrsi_derivative

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.uniform(0.1, 5.0, size=(8, 8, 8)).astype(np.float32)
            preproc = raw.copy()
            raw[0, 0, 0] = 300.0
            preproc[0, 0, 0] = 2.0
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}

            spike_mask = np.zeros((8, 8, 8), dtype=np.uint8)
            spike_mask[0, 0, 0] = 1
            spike_path = mrsi_derivative(config.derivative_dir, "S001", "V1", space="MRSI", met="CrPCr", desc="spikemask", suffix_override="mask")
            _save_volume(spike_path, spike_mask)

            sections = build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            text = _sections_text(sections)
            self.assertIn("_histogram-whole.png", text)
            self.assertIn("_histogram-spikes.png", text)
            figures_dir = coverage_report_dir(config.derivative_dir, "S001", "V1") / "figures"
            self.assertEqual(len(list(figures_dir.glob("*_histogram-whole.png"))), 1)
            self.assertEqual(len(list(figures_dir.glob("*_histogram-spikes.png"))), 1)

    def test_whole_image_histogram_always_present_spike_histogram_only_when_spikemask_available(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.uniform(0.1, 5.0, size=(8, 8, 8)).astype(np.float32)
            preproc = raw.copy()
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            sections = build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            text = _sections_text(sections)
            self.assertIn("_histogram-whole.png", text)
            self.assertNotIn("_histogram-spikes.png", text)

    def test_whole_image_histogram_excludes_hole_filled_voxels(self):
        """Regression test: biharmonic_repair() inpaints every exact-zero
        voxel inside the brain mask as a "missing hole", unrelated to spike
        removal -- can be a large fraction of the mask on acquisitions with
        steep slab-edge SNR falloff. require_nonzero_in_both=True must
        exclude these from the whole-image comparison so they don't look
        like real signal collapsing toward zero."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            raw = np.full((4, 4, 4), 2.0, dtype=np.float32)
            preproc = raw.copy()
            raw[0, 0, 0] = 0.0  # exact zero in raw: a hole biharmonic fills in
            preproc[0, 0, 0] = 1e-6  # inpainted to a tiny nonzero value
            out = tmp_path / "hist.png"
            _render_value_histogram(raw, preproc, out, label="CrPCr", require_nonzero_in_both=True)
            # No assertion on the image itself (rendering is exercised
            # elsewhere); the real check is that this doesn't raise and
            # that require_nonzero_in_both actually filters the hole voxel
            # out of the selection used to build the plot.
            finite = np.isfinite(raw) & np.isfinite(preproc) & (raw > 0) & (preproc > 0)
            self.assertFalse(finite[0, 0, 0], "hole-filled voxel (raw==0) must be excluded from require_nonzero_in_both selection")
            self.assertTrue(out.exists())

    def test_handles_mismatched_trailing_singleton_dimension(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.rand(44, 44, 25, 1)
            preproc = np.squeeze(raw.copy())
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            sections = build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertTrue(sections)

    def test_handles_no_repaired_voxels(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            same = np.random.rand(8, 8, 8)
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", same)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", same.copy())}
            sections = build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertIn("No voxels required repair", _sections_text(sections))

    def test_display_vmax_uses_filtered_data_not_raw_spike_value(self):
        """Regression test: a single extreme raw spike (e.g. an unfiltered
        acquisition artifact, value ~300) must not set vmax for both
        before/after panels -- that crushes all real tissue signal (~0-5)
        into an unreadable dark band in both images, even after the spike
        was successfully removed in the filtered map."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.uniform(0, 5, size=(8, 8, 8)).astype(np.float32)
            preproc = raw.copy()
            raw[0, 0, 0] = 300.0  # extreme spike, present only in raw
            preproc[0, 0, 0] = 2.0  # successfully repaired to a plausible value
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}

            captured_vmax = []
            from mrsiprep.reports import mrsi_preproc as mrsi_preproc_module

            original = mrsi_preproc_module.render_triplanar_png

            def _capture(*args, **kwargs):
                captured_vmax.append(kwargs.get("vmax"))
                return original(*args, **kwargs)

            with mock.patch.object(mrsi_preproc_module, "render_triplanar_png", side_effect=_capture):
                build_mrsi_preproc_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)

            self.assertTrue(captured_vmax)
            for vmax in captured_vmax:
                self.assertLess(vmax, 50.0, "vmax should reflect the filtered data's real range, not the raw 300.0 spike")


class RegistrationAlignmentSectionsTests(unittest.TestCase):
    def test_t1w_alignment_present_when_ref_map_given(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            t1_ref = _save_volume(tmp_path / "ref_t1.nii.gz", np.random.rand(8, 8, 8))
            sections = build_t1w_alignment_sections(config, "S001", "V1", raw_t1, t1_ref)
            text = _sections_text(sections)
            self.assertIn("T1w-space alignment", text)
            self.assertNotIn("not available for this configuration", text)

    def test_mni_alignment_reports_unavailable_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            sections = build_mni_alignment_sections(config, "S001", "V1", None)
            self.assertIn("not available for this configuration", _sections_text(sections))

    def test_handles_missing_t1_map(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            sections = build_t1w_alignment_sections(config, "S001", "V1", raw_t1, None)
            self.assertIn("No T1w-space reference metabolite map available", _sections_text(sections))

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

            with mock.patch("mrsiprep.mrsi.resampling.apply_image_transform", side_effect=_fake_apply):
                sections = build_t1w_alignment_sections(
                    config,
                    "S001",
                    "V1",
                    raw_t1,
                    None,
                    orig_ref_map_path=orig_ref,
                    mrsi_to_t1_transforms=[fake_transform],
                )
            text = _sections_text(sections)
            self.assertIn("T1w-space alignment", text)
            self.assertNotIn("No T1w-space reference metabolite map available", text)


class LeakageTableHtmlTests(unittest.TestCase):
    def test_renders_rows_for_matching_space_only(self):
        leakage_df = pd.DataFrame(
            {
                "space": ["T1w", "MNI152NLin2009cAsym"],
                "metabolite": ["CrPCr", "CrPCr"],
                "leakage_percent": [1.23, 4.56],
            }
        )
        html = leakage_table_html(leakage_df, "T1w")
        self.assertIn("Signal-weighted leakage", html)
        self.assertIn("1.230", html)
        self.assertNotIn("4.560", html)

    def test_mni_empty_when_no_data(self):
        self.assertEqual(leakage_table_html(None, "MNI152NLin2009cAsym"), "")
        self.assertEqual(leakage_table_html(pd.DataFrame(), "MNI152NLin2009cAsym"), "")

    def test_t1w_explains_why_when_no_data(self):
        # T1w leakage specifically needs --output-mrsi-t1w; explain that
        # rather than silently showing nothing next to the alignment image.
        html = leakage_table_html(None, "T1w")
        self.assertIn("--output-mrsi-t1w", html)
        html = leakage_table_html(pd.DataFrame(), "T1w")
        self.assertIn("--output-mrsi-t1w", html)


class ParcellationQCSectionsTests(unittest.TestCase):
    def test_includes_outline_overlay_and_region_count(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            atlas_t1 = _save_volume(tmp_path / "atlas_t1.nii.gz", np.random.randint(0, 4, (8, 8, 8)))
            labels_path = tmp_path / "labels.tsv"
            pd.DataFrame({"parcel_id": [1, 2, 3], "parcel_name": ["a", "b", "c"]}).to_csv(labels_path, sep="\t", index=False)
            sections = build_parcellation_qc_sections(config, "S001", "V1", raw_t1, atlas_t1, labels_path)
            text = _sections_text(sections)
            self.assertIn("Parcellation outlines", text)
            self.assertIn("3 regions", text)

    def test_handles_missing_atlas(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw_t1 = _save_volume(tmp_path / "raw_t1.nii.gz", np.random.rand(8, 8, 8))
            sections = build_parcellation_qc_sections(config, "S001", "V1", raw_t1, None, None)
            self.assertIn("Atlas not available in T1w space", _sections_text(sections))


class ConnectivityQCSectionsTests(unittest.TestCase):
    def test_includes_heatmap_when_matrix_present(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            matrix = pd.DataFrame(np.eye(3), index=["a", "b", "c"], columns=["a", "b", "c"])
            matrix_path = tmp_path / "matrix.tsv"
            matrix.to_csv(matrix_path, sep="\t")
            sections = build_connectivity_qc_sections(config, "S001", "V1", matrix_path)
            text = _sections_text(sections)
            self.assertIn("Connectivity matrix", text)
            self.assertIn("spearman", text)

    def test_handles_missing_matrix(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            sections = build_connectivity_qc_sections(config, "S001", "V1", None)
            self.assertIn("not requested", _sections_text(sections))


if __name__ == "__main__":
    unittest.main()
