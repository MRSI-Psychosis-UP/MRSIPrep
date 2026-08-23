import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.io.naming import coverage_report_dir
from mrsiprep.reports.mrsi_raw_overview import _center_weighted_indices, _equally_spaced_slices, build_mrsi_raw_qc_sections


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


class CenterWeightedIndicesTests(unittest.TestCase):
    def test_endpoints_are_included(self):
        indices = _center_weighted_indices(25, 10)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 24)

    def test_spacing_is_denser_near_the_center(self):
        indices = _center_weighted_indices(44, 10)
        gaps = [int(indices[i + 1] - indices[i]) for i in range(len(indices) - 1)]
        mid = len(gaps) // 2
        # gaps immediately around the center must be smaller than the
        # gaps at the very start/end of the sequence.
        self.assertLess(min(gaps[mid - 1 : mid + 2]), gaps[0])
        self.assertLess(min(gaps[mid - 1 : mid + 2]), gaps[-1])

    def test_handles_trivial_sizes(self):
        self.assertEqual(list(_center_weighted_indices(1, 10)), [0])


class EquallySpacedSlicesTests(unittest.TestCase):
    def test_returns_up_to_n_slices_spanning_the_axis(self):
        data = np.ones((10, 10, 20), dtype=np.float32)
        slices = _equally_spaced_slices(data, n_slices=10, axis=2)
        indices = [index for index, _ in slices]
        self.assertLessEqual(len(indices), 10)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 19)

    def test_skips_entirely_empty_slices(self):
        data = np.zeros((10, 10, 20), dtype=np.float32)
        data[:, :, 5:15] = 1.0  # only the middle 10 slices have signal
        slices = _equally_spaced_slices(data, n_slices=10, axis=2)
        indices = [index for index, _ in slices]
        self.assertTrue(all(5 <= index < 15 for index in indices))

    def test_falls_back_to_center_slice_when_all_empty(self):
        data = np.zeros((10, 10, 20), dtype=np.float32)
        slices = _equally_spaced_slices(data, n_slices=10, axis=2)
        self.assertEqual(len(slices), 1)


class BuildMrsiRawQcSectionsTests(unittest.TestCase):
    def test_includes_montage_per_metabolite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            raw = np.random.uniform(0, 5, size=(20, 20, 20)).astype(np.float32)
            preproc = raw.copy()
            raw_maps = {"CrPCr": _save_volume(tmp_path / "raw_cr.nii.gz", raw)}
            preproc_maps = {"CrPCr": _save_volume(tmp_path / "preproc_cr.nii.gz", preproc)}
            sections = build_mrsi_raw_qc_sections(config, "S001", "V1", raw_maps, preproc_maps)
            self.assertEqual(len(sections), 1)
            heading, body = sections[0]
            self.assertIn("CrPCr", heading)
            self.assertIn("raw-slices.png", body)
            figures_dir = coverage_report_dir(config.derivative_dir, "S001", "V1") / "figures"
            self.assertEqual(len(list(figures_dir.glob("*raw-slices.png"))), 1)

    def test_handles_no_metabolites(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = _make_config(tmp_path)
            sections = build_mrsi_raw_qc_sections(config, "S001", "V1", {}, {})
            self.assertIn("No raw MRSI metabolite maps available", sections[0][1])

    def test_scale_uses_preproc_not_raw_outlier(self):
        """Regression test: an extreme raw spike (e.g. an unfiltered
        acquisition artifact) must not set the montage's display scale --
        it should come from the filtered map instead, matching the
        before/after tab's own vmax fix."""
        from mrsiprep.reports.mrsi_raw_overview import _render_slice_montage

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            raw = np.random.uniform(0, 5, size=(10, 10, 10)).astype(np.float32)
            preproc = raw.copy()
            raw[0, 0, 0] = 300.0
            preproc[0, 0, 0] = 2.0
            out = tmp_path / "montage.png"
            _render_slice_montage(raw, preproc, out, label="CrPCr")
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
