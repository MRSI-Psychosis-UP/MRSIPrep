import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.reports.parcel_figures import (
    _atlas_canonical,
    _render_axial_grid,
    _value_volume,
    write_parcel_coverage_figure,
    write_parcel_crlb_figures,
    write_parcel_qc_figures,
)


def _save_nifti(path: Path, data: np.ndarray) -> None:
    nib.save(nib.Nifti1Image(data.astype(np.float32), np.eye(4)), path)


class RenderAxialGridTests(unittest.TestCase):
    """Calls the real matplotlib rendering, not the usual mocked-out version.

    Every other test in this file patches _render_axial_grid out entirely
    (it is expensive and its output isn't asserted on), which is exactly
    what let an axes.tolist()/colorbar bug through undetected: matplotlib's
    colorbar rejects the list-of-lists axes.tolist() gives for a 2D subplot
    grid, and it only raises inside the real call -- caught by actually
    running the pipeline end to end, not by any mocked unit test.
    """

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out_path = Path(self._tmpdir.name) / "grid.png"

    def test_renders_a_real_figure_with_a_shared_colorbar(self):
        rows = [("CrPCr", np.full((2, 2, 3), 5.0)), ("GluGln", np.full((2, 2, 3), 15.0))]
        _render_axial_grid(
            self.out_path, rows, indices=[0, 1, 2], title="test", cmap="viridis",
            vmin=0.0, vmax=20.0, colorbar_label="CRLB (%)",
        )
        self.assertTrue(self.out_path.exists())
        self.assertGreater(self.out_path.stat().st_size, 0)

    def test_renders_without_a_colorbar_label(self):
        """The categorical (green/red) caller path: no label, no colorbar,
        must not raise either."""
        rows = [("CrPCr", np.full((2, 2, 3), 1.0))]
        _render_axial_grid(
            self.out_path, rows, indices=[0, 1], title="test", cmap="RdYlGn", vmin=-1.0, vmax=1.0,
        )
        self.assertTrue(self.out_path.exists())

    def test_renders_with_a_single_row(self):
        """n_rows=1 is the shape most likely to make squeeze=False's 2D
        guarantee (and therefore the ravel() this needs) easy to forget."""
        rows = [("CrPCr", np.full((2, 2, 3), 5.0))]
        _render_axial_grid(
            self.out_path, rows, indices=[0, 1, 2], title="test", cmap="viridis",
            vmin=0.0, vmax=20.0, colorbar_label="CRLB (%)",
        )
        self.assertTrue(self.out_path.exists())


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
            "mrsiprep.reports.parcel_figures._render_axial_montage", return_value=self.tmp / "out.png"
        ) as render:
            write_parcel_coverage_figure(config, "01", "01", self.atlas_path, path)
        self.assertEqual(render.call_args.kwargs["vmin"], 0.0)
        self.assertEqual(render.call_args.kwargs["vmax"], 100.0)

    def test_passes_the_coverage_volume_and_slice_indices(self):
        path = self._write_tsv({"parcel_id": [1], "anatomical_coverage_percent": [50.0]})
        config = MagicMock(derivative_dir=self.tmp / "derivatives")
        with patch("mrsiprep.reports.parcel_figures.coverage_figure_derivative", return_value=self.tmp / "out.png"), patch(
            "mrsiprep.reports.parcel_figures._render_axial_montage", return_value=self.tmp / "out.png"
        ) as render:
            write_parcel_coverage_figure(config, "01", "01", self.atlas_path, path)
        volume, indices = render.call_args.args[1], render.call_args.args[2]
        self.assertEqual(volume.ndim, 3)
        # Zero-valued voxels are masked inside the renderer, not by the caller.
        self.assertEqual(len(indices), 10)


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

    def _crlb_map(self, name: str, shape=(2, 2, 3), value: float = 5.0) -> Path:
        path = self.tmp / f"crlb-{name}.nii.gz"
        _save_nifti(path, np.full(shape, value))
        return path

    def test_returns_empty_for_empty_dataframe(self):
        path = self._write_tsv({"parcel_id": [], "mean_crlb": [], "metabolite": []})
        self.assertEqual(write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"]), [])

    def test_returns_empty_when_metabolite_column_missing(self):
        path = self._write_tsv({"parcel_id": [1], "anatomical_coverage_percent": [90.0]})
        self.assertEqual(write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"]), [])

    def test_returns_empty_without_a_t1_to_mni_transform(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr")}
        self.assertEqual(
            write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=None, crlb_maps=crlb_maps), []
        )

    def test_returns_empty_without_crlb_maps(self):
        """No MNI-space CRLB derivatives (template output not requested):
        skip the figure rather than resample a second time for a space
        nothing else in the run produced."""
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        self.assertEqual(
            write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=None), []
        )

    def test_writes_one_grid_with_a_row_per_metabolite_showing_the_voxelwise_map(self):
        path = self._write_tsv(
            {
                "parcel_id": [1, 2, 1, 2],
                "mean_crlb": [5.0, 30.0, float("nan"), 10.0],
                "metabolite": ["CrPCr", "CrPCr", "GluGln", "GluGln"],
            }
        )
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        fake_atlas[1, 1, :] = 2
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr", value=7.0), "GluGln": self._crlb_map("GluGln", value=15.0)}
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures.coverage_figure_derivative", side_effect=lambda *a, **k: self.tmp / f"{k.get('met', 'crlbgrid')}.png"
        ), patch("mrsiprep.reports.parcel_figures._render_axial_grid") as grid:
            outputs = write_parcel_crlb_figures(
                self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=crlb_maps
            )

        # A single figure with one row per metabolite, not one figure each:
        # the panel exists to compare metabolites at identical anatomy.
        self.assertEqual(len(outputs), 1)
        grid.assert_called_once()
        rows = grid.call_args.args[1]
        self.assertEqual([label for label, _volume in rows], ["CrPCr", "GluGln"])
        # The row holds the raw voxel values, not a per-parcel summary.
        crpcr_volume = rows[0][1]
        np.testing.assert_allclose(crpcr_volume, 7.0)
        # Semi-transparent so the template underneath places the map.
        self.assertLess(grid.call_args.kwargs["alpha"], 1.0)
        # A continuous quantity, so it gets a colorbar (unlike the old
        # categorical green/red overlay, which would misrepresent one).
        self.assertIn("CRLB", grid.call_args.kwargs["colorbar_label"])

    def test_colorscale_uses_the_runs_own_crlb_threshold(self):
        """vmax is the run's own quality threshold, not an arbitrary display
        cap, so the colour scale means the same thing the pass/fail decision
        used."""
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr")}
        config = MagicMock(derivative_dir=self.tmp / "derivatives", crlb_max=42.0)
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures._render_axial_grid"
        ) as grid:
            write_parcel_crlb_figures(config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=crlb_maps)
        self.assertEqual(grid.call_args.kwargs["vmax"], 42.0)

    def test_removes_superseded_per_metabolite_figures(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        figures = self.tmp / "figures"
        figures.mkdir(exist_ok=True)
        stale = figures / "sub-01_met-CrPCr_desc-parcelcrlbquality.png"
        stale.write_bytes(b"x")
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr")}
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures.coverage_figure_derivative",
            return_value=figures / "sub-01_desc-parcelcrlbquality.png",
        ), patch("mrsiprep.reports.parcel_figures._render_axial_grid"):
            write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=crlb_maps)
        self.assertFalse(stale.exists(), "the grid replaces these, so they must not linger")

    def test_skips_metabolite_with_no_crlb_map(self):
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        fake_atlas = np.array([[[1]]])
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures._render_axial_grid"
        ) as grid:
            outputs = write_parcel_crlb_figures(
                self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps={"NAANAAG": self._crlb_map("NAANAAG")}
            )

        self.assertEqual(outputs, [])
        grid.assert_not_called()

    def test_skips_metabolite_whose_crlb_map_is_on_a_different_grid(self):
        """A shape mismatch means resampling and this figure disagree on the
        resolution used; draw nothing rather than misaligned voxels."""
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        mismatched = self._crlb_map("CrPCr", shape=(4, 4, 4))
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures._render_axial_grid"
        ) as grid:
            outputs = write_parcel_crlb_figures(
                self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps={"CrPCr": mismatched}
            )
        self.assertEqual(outputs, [])
        grid.assert_not_called()

    def test_draws_on_black_when_the_template_underlay_cannot_be_fetched(self):
        """The underlay is decoration: a template fetch failure must not take
        the CRLB figure down with it."""
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr")}
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.config.templates.template_t1w", side_effect=RuntimeError("network unavailable")
        ), patch("mrsiprep.reports.parcel_figures._render_axial_grid") as grid:
            outputs = write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=crlb_maps)

        self.assertEqual(len(outputs), 1)
        self.assertIsNone(grid.call_args.kwargs["underlay"])

    def test_a_stale_figure_that_cannot_be_deleted_does_not_fail_the_write(self):
        """Best-effort cleanup: a read-only or concurrently-held stale file
        is not a reason to fail the figure that replaces it."""
        path = self._write_tsv({"parcel_id": [1], "mean_crlb": [5.0], "metabolite": ["CrPCr"]})
        figures = self.tmp / "figures"
        figures.mkdir(exist_ok=True)
        stale = figures / "sub-01_met-CrPCr_desc-parcelcrlbquality.png"
        stale.write_bytes(b"x")
        fake_atlas = np.zeros((2, 2, 3), dtype=int)
        fake_atlas[0, 0, :] = 1
        crlb_maps = {"CrPCr": self._crlb_map("CrPCr")}
        with patch("mrsiprep.reports.parcel_figures._resample_atlas_to_mni", return_value=(fake_atlas, np.eye(4))), patch(
            "mrsiprep.reports.parcel_figures.coverage_figure_derivative",
            return_value=figures / "sub-01_desc-parcelcrlbquality.png",
        ), patch("mrsiprep.reports.parcel_figures._render_axial_grid"), patch(
            "pathlib.Path.unlink", side_effect=OSError("permission denied")
        ):
            outputs = write_parcel_crlb_figures(self.config, "01", "01", self.atlas_t1, path, t1_to_mni=["x"], crlb_maps=crlb_maps)
        self.assertEqual(len(outputs), 1)


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
