import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.reports.parcel_figures import (
    CRLB_QUALITY_THRESHOLD,
    _atlas_canonical,
    _value_volume,
    write_parcel_coverage_figure,
    write_parcel_crlb_figures,
    write_parcel_qc_figures,
)


class AtlasCanonicalTests(unittest.TestCase):
    def test_rounds_and_casts_to_int32(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "atlas.nii.gz"
            # No singleton dimensions, so .squeeze() is a genuine no-op here
            # (as it is for real, fully 3D anatomical volumes) rather than
            # collapsing an axis and making the expected shape ambiguous.
            data = np.array([[[1.4, 2.6], [3.5, 4.5]], [[0.4, 0.5], [1.5, 2.5]]], dtype=np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            atlas = _atlas_canonical(path)
        self.assertEqual(atlas.dtype, np.int32)
        self.assertEqual(atlas.shape, (2, 2, 2))
        np.testing.assert_array_equal(atlas, np.rint(data).astype(np.int32))


class ValueVolumeTests(unittest.TestCase):
    def test_maps_parcel_ids_to_values(self):
        atlas = np.array([[1, 1, 2], [2, 0, 0]])
        volume = _value_volume(atlas, {1: 10.0, 2: 20.0})
        np.testing.assert_array_equal(volume, np.array([[10.0, 10.0, 20.0], [20.0, 0.0, 0.0]]))

    def test_none_and_nan_values_are_skipped(self):
        atlas = np.array([[1, 2]])
        volume = _value_volume(atlas, {1: None, 2: float("nan")})
        np.testing.assert_array_equal(volume, np.array([[0.0, 0.0]]))


class WriteParcelCoverageFigureTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.atlas_path = self.tmp / "atlas.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)), self.atlas_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_tsv(self, rows):
        path = self.tmp / "parcel_qc.tsv"
        pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
        return path

    def test_returns_none_for_empty_dataframe(self):
        path = self._write_tsv({"parcel_id": [], "anatomical_coverage_percent": []})
        self.assertIsNone(write_parcel_coverage_figure(None, "01", "01", self.atlas_path, path))

    def test_returns_none_when_coverage_column_missing(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0]})
        self.assertIsNone(write_parcel_coverage_figure(None, "01", "01", self.atlas_path, path))

    def test_pins_colorbar_to_full_0_100_range(self):
        path = self._write_tsv({"parcel_id": [1], "anatomical_coverage_percent": [100.0]})
        config = MagicMock(derivative_dir=self.tmp / "derivatives")
        with patch("mrsiprep.reports.parcel_figures.coverage_figure_derivative", return_value=self.tmp / "out.png"), patch(
            "mrsiprep.reports.parcel_figures.render_triplanar_png", return_value=self.tmp / "out.png"
        ) as render:
            write_parcel_coverage_figure(config, "01", "01", self.atlas_path, path)
        self.assertEqual(render.call_args.kwargs["vmin"], 0.0)
        self.assertEqual(render.call_args.kwargs["vmax"], 100.0)

    def test_masks_zero_and_below_voxels(self):
        path = self._write_tsv({"parcel_id": [1], "anatomical_coverage_percent": [50.0]})
        config = MagicMock(derivative_dir=self.tmp / "derivatives")
        with patch("mrsiprep.reports.parcel_figures.coverage_figure_derivative", return_value=self.tmp / "out.png"), patch(
            "mrsiprep.reports.parcel_figures.render_triplanar_png", return_value=self.tmp / "out.png"
        ) as render:
            write_parcel_coverage_figure(config, "01", "01", self.atlas_path, path)
        masked_slices = render.call_args.kwargs["background_slices"]
        for plane_data in masked_slices.values():
            self.assertIsInstance(plane_data, np.ma.MaskedArray)


class WriteParcelCrlbFiguresTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.atlas_t1 = self.tmp / "atlas_t1.nii.gz"
        self.atlas_t1.touch()
        self.config = MagicMock(derivative_dir=self.tmp / "derivatives")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_tsv(self, rows):
        path = self.tmp / "parcel_qc.tsv"
        pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
        return path

    def test_returns_empty_for_empty_dataframe(self):
        path = self._write_tsv({"parcel_id": [], "mean_crlb": [], "metabolite": []})
        self.assertEqual(write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"]), [])

    def test_returns_empty_when_required_columns_missing(self):
        path = self._write_tsv({"parcel_id": [1], "anatomical_coverage_percent": [90.0]})
        self.assertEqual(write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"]), [])

    def test_returns_empty_without_a_t1_to_mni_transform(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        self.assertEqual(write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=None), [])

    def test_writes_one_figure_per_metabolite_with_a_valid_crlb(self):
        path = self._write_tsv(
            {
                "parcel_id": [1, 2, 1, 2],
                "mean_crlb": [5.0, 30.0, float("nan"), 10.0],
                "metabolite": ["CrPCr", "CrPCr", "GluGln", "GluGln"],
            }
        )
        fake_atlas = np.array([[1, 2]])
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures.coverage_figure_derivative", side_effect=lambda *a, **k: self.tmp / f"{k['met']}.png"
        ), patch("nibabel.Nifti1Image"), patch("nilearn.plotting.plot_glass_brain") as plot_glass_brain:
            display = MagicMock()
            plot_glass_brain.return_value = display
            outputs = write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"])

        self.assertEqual(len(outputs), 2)
        self.assertEqual(plot_glass_brain.call_count, 2)
        self.assertEqual(display.savefig.call_count, 2)

    def test_skips_metabolite_with_no_valid_crlb_values(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [float("nan")], "metabolite": ["CrPCr"]})
        fake_atlas = np.array([[1]])
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "nilearn.plotting.plot_glass_brain"
        ) as plot_glass_brain:
            outputs = write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"])

        self.assertEqual(outputs, [])
        plot_glass_brain.assert_not_called()

    def test_thresholds_reliable_vs_unreliable_by_quality_threshold(self):
        path = self._write_tsv(
            {
                "parcel_id": [1, 2],
                "mean_crlb": [CRLB_QUALITY_THRESHOLD - 1, CRLB_QUALITY_THRESHOLD + 1],
                "metabolite": ["CrPCr", "CrPCr"],
            }
        )
        fake_atlas = np.array([[1, 2]])
        captured = {}

        def fake_value_volume(atlas, mapping):
            captured["mapping"] = mapping
            return np.zeros_like(atlas, dtype=np.float32)

        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures._value_volume", side_effect=fake_value_volume
        ), patch("nibabel.Nifti1Image"), patch("nilearn.plotting.plot_glass_brain", return_value=MagicMock()):
            write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"])

        self.assertEqual(captured["mapping"], {1: 1.0, 2: -1.0})


class WriteParcelQcFiguresTests(unittest.TestCase):
    def test_returns_empty_when_atlas_t1_missing(self):
        self.assertEqual(write_parcel_qc_figures(None, "01", "01", None, Path("/tmp/x.tsv")), [])

    def test_returns_empty_when_tsv_missing(self):
        self.assertEqual(write_parcel_qc_figures(None, "01", "01", Path("/tmp/atlas.nii.gz"), None), [])

    def test_returns_empty_when_tsv_does_not_exist_on_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_tsv = Path(tmpdir) / "missing.tsv"
            self.assertEqual(write_parcel_qc_figures(None, "01", "01", Path(tmpdir) / "atlas.nii.gz", missing_tsv), [])

    def test_combines_coverage_and_crlb_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            atlas_t1 = Path(tmpdir) / "atlas_t1.nii.gz"
            atlas_t1.touch()
            tsv = Path(tmpdir) / "parcel_qc.tsv"
            tsv.touch()
            with patch("mrsiprep.reports.parcel_figures.write_parcel_coverage_figure", return_value=Path("coverage.png")) as coverage_fn, patch(
                "mrsiprep.reports.parcel_figures.write_parcel_crlb_figures", return_value=[Path("crlb1.png"), Path("crlb2.png")]
            ):
                outputs = write_parcel_qc_figures(None, "01", "01", atlas_t1, tsv, atlas_mrsi=None)

        self.assertEqual(outputs, [Path("coverage.png"), Path("crlb1.png"), Path("crlb2.png")])
        # atlas_mrsi=None -> the coverage figure falls back to atlas_t1.
        self.assertEqual(coverage_fn.call_args[0][3], atlas_t1)

    def test_skips_coverage_output_when_it_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            atlas_t1 = Path(tmpdir) / "atlas_t1.nii.gz"
            atlas_t1.touch()
            tsv = Path(tmpdir) / "parcel_qc.tsv"
            tsv.touch()
            with patch("mrsiprep.reports.parcel_figures.write_parcel_coverage_figure", return_value=None), patch(
                "mrsiprep.reports.parcel_figures.write_parcel_crlb_figures", return_value=[]
            ):
                outputs = write_parcel_qc_figures(None, "01", "01", atlas_t1, tsv)

        self.assertEqual(outputs, [])


if __name__ == "__main__":
    unittest.main()
