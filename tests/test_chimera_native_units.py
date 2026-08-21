import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.parcellation.chimera_native import _labels_from_image, run_chimera_parcellation

MODULE = "mrsiprep.parcellation.chimera_native"


def _config(root: Path, **overrides):
    base = dict(
        bids_dir=root / "bids",
        output_dir=root / "out",
        freesurfer_dir=root / "fs",
        bids_filters=None,
        overwrite=False,
        overwrite_chimera=False,
        chimera_scheme="LFMIHIFIF",
        chimera_scale=3,
        chimera_grow=2,
        nthreads=4,
        verbose=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _save(path: Path, values, shape=(2, 2, 2)):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(values, dtype=np.float32).reshape(shape)
    nib.save(nib.Nifti1Image(data, np.eye(4)), path)
    return path


def _fake_apply(*args, **_kwargs):
    """Copy rather than re-encode: the source may be .nii while the
    derivative name is .nii.gz, and nibabel would reject the mismatch."""
    import shutil

    out = Path(args[3])
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args[1], out)
    return out


class _Harness:
    """Patches every external dependency of run_chimera_parcellation."""

    def __init__(self, root, *, source_atlas=None, raw_t1=None, dir_valid=True):
        self.root = root
        self.layout = SimpleNamespace(
            chimera_atlas=lambda *a, **k: source_atlas,
            raw_t1=lambda *a, **k: raw_t1,
        )
        self.dir_valid = dir_valid
        self.produced = source_atlas

    def __enter__(self):
        self.patches = [
            patch(f"{MODULE}.BIDSLayout", return_value=self.layout),
            patch(f"{MODULE}.subject_dir_valid", return_value=self.dir_valid),
            patch(f"{MODULE}.freesurfer_subject_id", return_value="sub-S001"),
            patch(f"{MODULE}.run_recon_all"),
            patch(f"{MODULE}.run_chimera", return_value=self.produced),
            patch(f"{MODULE}.apply_image_transform", side_effect=_fake_apply),
            patch(f"{MODULE}.copy_labels"),
        ]
        self.mocks = SimpleNamespace(
            layout_cls=self.patches[0].start(),
            subject_dir_valid=self.patches[1].start(),
            freesurfer_subject_id=self.patches[2].start(),
            run_recon_all=self.patches[3].start(),
            run_chimera=self.patches[4].start(),
            apply_image_transform=self.patches[5].start(),
            copy_labels=self.patches[6].start(),
        )
        return self.mocks

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False


class LabelsFromImageTests(unittest.TestCase):
    def test_writes_one_row_per_nonzero_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = _save(root / "atlas.nii.gz", [0, 1, 1, 2, 2, 3, 0, 0])
            labels = root / "labels.tsv"

            _labels_from_image(image, labels)

            with open(labels, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([r["parcel_id"] for r in rows], ["1", "2", "3"])

    def test_background_zero_is_never_a_parcel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = _save(root / "atlas.nii.gz", [0] * 7 + [5])
            labels = root / "labels.tsv"

            _labels_from_image(image, labels)

            with open(labels, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([r["parcel_id"] for r in rows], ["5"])

    def test_all_background_yields_no_parcels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            image = _save(root / "atlas.nii.gz", [0] * 8)
            labels = root / "labels.tsv"

            _labels_from_image(image, labels)

            with open(labels, newline="", encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle, delimiter="\t")), [])


class RunChimeraParcellationTests(unittest.TestCase):
    def test_cached_atlas_skips_recon_all_and_chimera_entirely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [1] * 8)

            with _Harness(root, source_atlas=source) as mocks:
                result = run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.run_recon_all.assert_not_called()
            mocks.run_chimera.assert_not_called()
            self.assertTrue(result.atlas_t1.exists())

    def test_missing_atlas_runs_chimera(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            produced = _save(root / "produced.nii.gz", [1] * 8)
            raw_t1 = _save(root / "t1.nii.gz", [1] * 8)

            harness = _Harness(root, source_atlas=None, raw_t1=raw_t1)
            harness.produced = produced
            with harness as mocks:
                run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.run_chimera.assert_called_once()

    def test_recon_all_runs_only_when_the_freesurfer_subject_dir_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            produced = _save(root / "produced.nii.gz", [1] * 8)
            raw_t1 = _save(root / "t1.nii.gz", [1] * 8)

            for dir_valid, expected in ((True, 0), (False, 1)):
                harness = _Harness(root, source_atlas=None, raw_t1=raw_t1, dir_valid=dir_valid)
                harness.produced = produced
                with harness as mocks:
                    run_chimera_parcellation(
                        _config(root, output_dir=root / f"out-{dir_valid}"), "S001", "V1", root / "ref.nii.gz", []
                    )
                self.assertEqual(mocks.run_recon_all.call_count, expected, msg=f"dir_valid={dir_valid}")

    def test_missing_raw_t1_raises_before_running_anything(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with _Harness(root, source_atlas=None, raw_t1=None) as mocks:
                with self.assertRaisesRegex(FileNotFoundError, "Missing raw T1w required for Chimera"):
                    run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.run_chimera.assert_not_called()
            mocks.run_recon_all.assert_not_called()

    def test_overwrite_bypasses_the_cached_atlas_lookup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            produced = _save(root / "produced.nii.gz", [1] * 8)
            raw_t1 = _save(root / "t1.nii.gz", [1] * 8)

            for flag in ("overwrite", "overwrite_chimera"):
                cached = _save(root / f"cached-{flag}.nii.gz", [1] * 8)
                harness = _Harness(root, source_atlas=cached, raw_t1=raw_t1)
                harness.produced = produced
                with harness as mocks:
                    run_chimera_parcellation(
                        _config(root, output_dir=root / f"out-{flag}", **{flag: True}),
                        "S001", "V1", root / "ref.nii.gz", [],
                    )
                # chimera_atlas() returned a cached path, but the rerun flag
                # must ignore it and regenerate instead.
                mocks.run_chimera.assert_called_once()
                self.assertTrue(mocks.run_chimera.call_args.kwargs["force"])

    def test_result_carries_chimera_mode_and_derived_atlas_name_and_scale(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [1] * 8)

            with _Harness(root, source_atlas=source):
                result = run_chimera_parcellation(
                    _config(root, chimera_scheme="LFMIHIFIS", chimera_scale=1), "S001", "V1", root / "ref.nii.gz", []
                )

            self.assertEqual(result.mode, "chimera")
            self.assertEqual(result.atlas_name, "chimeraLFMIHIFIS")
            self.assertEqual(result.scale, "scale1")

    def test_atlas_is_resampled_into_mrsi_space_with_label_interpolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [1] * 8)
            transforms = [root / "xfm.mat"]

            with _Harness(root, source_atlas=source) as mocks:
                result = run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", transforms)

            # A parcellation is categorical: nearest-label, never linear.
            self.assertEqual(mocks.apply_image_transform.call_args.kwargs["interpolation"], "genericLabel")
            self.assertEqual(mocks.apply_image_transform.call_args.args[2], transforms)
            self.assertTrue(result.atlas_mrsi.exists())

    def test_sidecar_labels_are_copied_when_they_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [1] * 8)
            source.with_suffix("").with_suffix(".tsv").write_text("index\tname\n1\tA\n", encoding="utf-8")

            with _Harness(root, source_atlas=source) as mocks:
                run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.copy_labels.assert_called_once()

    def test_labels_are_derived_from_the_image_when_no_sidecar_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [0, 1, 1, 2, 2, 2, 0, 0])

            with _Harness(root, source_atlas=source) as mocks:
                result = run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.copy_labels.assert_not_called()
            with open(result.labels, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([r["parcel_id"] for r in rows], ["1", "2"])

    def test_plain_nii_sidecar_name_is_resolved_without_double_stripping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            # A .nii (not .nii.gz) source: only one suffix should be replaced.
            source = root / "source.nii"
            source.parent.mkdir(parents=True, exist_ok=True)
            nib.save(nib.Nifti1Image(np.ones((2, 2, 2), dtype=np.float32), np.eye(4)), source)
            (root / "source.tsv").write_text("index\tname\n1\tA\n", encoding="utf-8")

            with _Harness(root, source_atlas=source) as mocks:
                run_chimera_parcellation(_config(root), "S001", "V1", root / "ref.nii.gz", [])

            mocks.copy_labels.assert_called_once()

    def test_existing_outputs_are_not_recopied_or_retransformed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = _save(root / "source.nii.gz", [1] * 8)
            config = _config(root)

            with _Harness(root, source_atlas=source):
                run_chimera_parcellation(config, "S001", "V1", root / "ref.nii.gz", [])

            with _Harness(root, source_atlas=source) as mocks:
                run_chimera_parcellation(config, "S001", "V1", root / "ref.nii.gz", [])

            mocks.apply_image_transform.assert_not_called()


if __name__ == "__main__":
    unittest.main()
