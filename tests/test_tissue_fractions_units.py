import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.tissue.fractions import (
    copy_tissue_to_derivatives,
    load_existing_cat12,
    resample_tissue_to_mrsi,
)


def _config(root: Path, **overrides):
    base = dict(
        bids_dir=root / "bids",
        derivative_dir=root / "derivatives",
        bids_filters=None,
        overwrite=False,
        overwrite_seg=False,
        nthreads=4,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _save(path: Path, value=1.0, shape=(2, 2, 2)):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.full(shape, value, dtype=np.float32), np.eye(4)), path)
    return path


class LoadExistingCat12Tests(unittest.TestCase):
    def _layout(self, mapping):
        """Fake BIDSLayout whose cat12_probseg returns mapping[index]."""
        layout = SimpleNamespace(cat12_probseg=lambda subject, session, index: mapping.get(index))
        return patch(
            "mrsiprep.tissue.fractions.BIDSLayout",
            return_value=layout,
            **{"from_config.return_value": layout},
        )

    def test_returns_all_three_maps_keyed_by_tissue_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = {i: _save(root / f"p{i}.nii.gz") for i in (1, 2, 3)}
            with self._layout(paths):
                result = load_existing_cat12(_config(root), "S001", "V1")

            self.assertEqual(result, {"GM": paths[1], "WM": paths[2], "CSF": paths[3]})

    def test_p1_p2_p3_map_to_gm_wm_csf_in_that_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = {i: _save(root / f"p{i}.nii.gz") for i in (1, 2, 3)}
            with self._layout(paths):
                result = load_existing_cat12(_config(root), "S001", "V1")

            self.assertEqual(result["GM"].name, "p1.nii.gz")
            self.assertEqual(result["WM"].name, "p2.nii.gz")
            self.assertEqual(result["CSF"].name, "p3.nii.gz")

    def test_missing_map_raises_naming_the_absent_tissue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = {1: _save(root / "p1.nii.gz"), 2: _save(root / "p2.nii.gz"), 3: None}
            with self._layout(paths):
                with self.assertRaisesRegex(FileNotFoundError, "CSF"):
                    load_existing_cat12(_config(root), "S001", "V1")

    def test_path_that_is_returned_but_does_not_exist_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = {1: _save(root / "p1.nii.gz"), 2: root / "gone.nii.gz", 3: _save(root / "p3.nii.gz")}
            with self._layout(paths):
                with self.assertRaisesRegex(FileNotFoundError, "WM"):
                    load_existing_cat12(_config(root), "S001", "V1")

    def test_every_missing_tissue_is_listed_in_one_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self._layout({1: None, 2: None, 3: None}):
                with self.assertRaises(FileNotFoundError) as ctx:
                    load_existing_cat12(_config(root), "S001", "V1")

            message = str(ctx.exception)
            for label in ("GM", "WM", "CSF"):
                self.assertIn(label, message)

    def test_layout_is_built_from_the_run_config(self):
        # from_config() carries bids_filters *and* the nucleus's metabolite
        # aliases, so passing the config through is what keeps both correct.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = {i: _save(root / f"p{i}.nii.gz") for i in (1, 2, 3)}
            layout = SimpleNamespace(cat12_probseg=lambda subject, session, index: paths.get(index))
            config = _config(root, bids_filters={"acquisition": "highres"})

            with patch(
                "mrsiprep.tissue.fractions.BIDSLayout",
                return_value=layout,
                **{"from_config.return_value": layout},
            ) as layout_cls:
                load_existing_cat12(config, "S001", "V1")

            layout_cls.from_config.assert_called_once_with(config)


class CopyTissueToDerivativesTests(unittest.TestCase):
    def test_each_map_is_copied_under_the_derivatives_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources = {label: _save(root / f"{label}.nii.gz", value=i + 1) for i, label in enumerate(("GM", "WM", "CSF"))}

            result = copy_tissue_to_derivatives(_config(root), "S001", "V1", sources)

            self.assertEqual(set(result), {"GM", "WM", "CSF"})
            for label, target in result.items():
                self.assertTrue(target.exists())
                self.assertIn(str(root / "derivatives"), str(target))
                self.assertNotEqual(target, sources[label])

    def test_voxel_data_survives_the_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "GM.nii.gz", value=0.75)

            result = copy_tissue_to_derivatives(_config(root), "S001", "V1", {"GM": source})

            np.testing.assert_allclose(np.asanyarray(nib.load(str(result["GM"])).dataobj), 0.75)

    def test_output_is_written_as_float32(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "GM.nii.gz")

            result = copy_tissue_to_derivatives(_config(root), "S001", "V1", {"GM": source})

            self.assertEqual(nib.load(str(result["GM"])).get_data_dtype(), np.float32)

    def test_existing_target_is_reused_without_recopying(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "GM.nii.gz", value=1.0)
            config = _config(root)

            first = copy_tissue_to_derivatives(config, "S001", "V1", {"GM": source})["GM"]
            _save(first, value=9.0)  # sentinel: a real recopy would overwrite this
            second = copy_tissue_to_derivatives(config, "S001", "V1", {"GM": source})["GM"]

            self.assertEqual(first, second)
            np.testing.assert_allclose(np.asanyarray(nib.load(str(second)).dataobj), 9.0)

    def test_overwrite_seg_forces_a_recopy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "GM.nii.gz", value=1.0)

            first = copy_tissue_to_derivatives(_config(root), "S001", "V1", {"GM": source})["GM"]
            _save(first, value=9.0)
            second = copy_tissue_to_derivatives(_config(root, overwrite_seg=True), "S001", "V1", {"GM": source})["GM"]

            np.testing.assert_allclose(np.asanyarray(nib.load(str(second)).dataobj), 1.0)

    def test_global_overwrite_also_forces_a_recopy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "GM.nii.gz", value=1.0)

            first = copy_tissue_to_derivatives(_config(root), "S001", "V1", {"GM": source})["GM"]
            _save(first, value=9.0)
            second = copy_tissue_to_derivatives(_config(root, overwrite=True), "S001", "V1", {"GM": source})["GM"]

            np.testing.assert_allclose(np.asanyarray(nib.load(str(second)).dataobj), 1.0)

    def test_empty_input_returns_empty_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(copy_tissue_to_derivatives(_config(Path(tmpdir)), "S001", "V1", {}), {})


class ResampleTissueToMrsiTests(unittest.TestCase):
    def test_each_map_is_resampled_onto_the_mrsi_reference_grid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sources = {"GM": _save(root / "GM.nii.gz"), "WM": _save(root / "WM.nii.gz")}
            reference = _save(root / "ref.nii.gz")
            transforms = [root / "xfm.mat"]

            with patch(
                "mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: a[3]
            ) as apply_mock:
                result = resample_tissue_to_mrsi(_config(root), "S001", "V1", sources, reference, transforms)

            self.assertEqual(set(result), {"GM", "WM"})
            self.assertEqual(apply_mock.call_count, 2)
            for call in apply_mock.call_args_list:
                self.assertEqual(call.args[0], reference)
                self.assertEqual(call.args[2], transforms)

    def test_linear_interpolation_is_used_for_probability_maps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference = _save(root / "ref.nii.gz")

            with patch(
                "mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: a[3]
            ) as apply_mock:
                resample_tissue_to_mrsi(
                    _config(root), "S001", "V1", {"GM": _save(root / "GM.nii.gz")}, reference, []
                )

            self.assertEqual(apply_mock.call_args.kwargs["interpolation"], "linear")

    def test_nthreads_is_forwarded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference = _save(root / "ref.nii.gz")

            with patch(
                "mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: a[3]
            ) as apply_mock:
                resample_tissue_to_mrsi(
                    _config(root, nthreads=12), "S001", "V1", {"GM": _save(root / "GM.nii.gz")}, reference, []
                )

            self.assertEqual(apply_mock.call_args.kwargs["threads"], 12)

    def test_existing_target_short_circuits_the_transform(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference = _save(root / "ref.nii.gz")
            sources = {"GM": _save(root / "GM.nii.gz")}
            config = _config(root)

            with patch("mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: _save(a[3])):
                first = resample_tissue_to_mrsi(config, "S001", "V1", sources, reference, [])["GM"]

            with patch("mrsiprep.tissue.fractions.apply_image_transform") as apply_mock:
                second = resample_tissue_to_mrsi(config, "S001", "V1", sources, reference, [])["GM"]

            apply_mock.assert_not_called()
            self.assertEqual(first, second)

    def test_overwrite_seg_forces_the_transform_to_rerun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reference = _save(root / "ref.nii.gz")
            sources = {"GM": _save(root / "GM.nii.gz")}

            with patch("mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: _save(a[3])):
                resample_tissue_to_mrsi(_config(root), "S001", "V1", sources, reference, [])

            with patch(
                "mrsiprep.tissue.fractions.apply_image_transform", side_effect=lambda *a, **k: _save(a[3])
            ) as apply_mock:
                resample_tissue_to_mrsi(_config(root, overwrite_seg=True), "S001", "V1", sources, reference, [])

            apply_mock.assert_called_once()

    def test_empty_input_returns_empty_mapping_without_transforming(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("mrsiprep.tissue.fractions.apply_image_transform") as apply_mock:
                result = resample_tissue_to_mrsi(
                    _config(root), "S001", "V1", {}, _save(root / "ref.nii.gz"), []
                )

            self.assertEqual(result, {})
            apply_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
