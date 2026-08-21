"""Tests for parcellation/atlas_registry.py -- previously entirely
untested. Bundled-atlas discovery tests patch ATLAS_DATA_DIR itself to a
controlled tempdir rather than relying on whatever atlas directories
happen to be committed to mrsiprep/data/atlas/ (which can and does change).
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.parcellation.atlas_registry import (
    _atlas_key,
    _bundled_atlas_label,
    _find_bundled_atlas,
    _save_nifti_atomic,
    available_bundled_atlases,
    load_mni_atlas,
)


class SaveNiftiAtomicTests(unittest.TestCase):
    def test_writes_to_final_path_and_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "atlas.nii.gz"
            img = nib.Nifti1Image(np.zeros((2, 2, 2), dtype=np.float32), np.eye(4))
            _save_nifti_atomic(img, out_path)
            self.assertTrue(out_path.exists())
            self.assertEqual(list(Path(tmpdir).glob(".atlas.nii.gz.tmp-*")), [])


class AtlasKeyTests(unittest.TestCase):
    def test_strips_non_alnum_and_lowercases(self):
        self.assertEqual(_atlas_key("Chimera-LFMIHIFIS_Scale3"), "chimeralfmihifis3")

    def test_strips_the_literal_word_scale_even_without_a_delimiter(self):
        self.assertEqual(_atlas_key("scale3"), "3")


class BundledAtlasLabelTests(unittest.TestCase):
    def test_new_style_delimited_name_just_strips_hyphens(self):
        self.assertEqual(_bundled_atlas_label("chimera-LFMIHIFIS_scale3"), "chimeraLFMIHIFIS_scale3")

    def test_old_style_bare_number_with_lausanne_scheme_gets_scale_word(self):
        self.assertEqual(_bundled_atlas_label("chimera-LFMIHIFIS-3"), "chimeraLFMIHIFIS_scale3")

    def test_old_style_bare_number_with_non_lausanne_scheme_has_no_scale_word(self):
        self.assertEqual(_bundled_atlas_label("chimera-SFMIHIFIS-3"), "chimeraSFMIHIFIS_3")

    def test_two_part_name_is_unaffected_by_the_bare_number_special_case(self):
        # len(parts) < 3 here, so this falls straight to the plain
        # hyphen-strip fallback even though "3" looks like a trailing count.
        self.assertEqual(_bundled_atlas_label("atlas-3"), "atlas3")


class BundledAtlasFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.atlas_dir = Path(self._tmpdir.name) / "atlas"
        patcher = patch("mrsiprep.parcellation.atlas_registry.ATLAS_DATA_DIR", self.atlas_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_atlas_dir(self, name: str, with_image: bool = True, with_labels: bool = True) -> Path:
        d = self.atlas_dir / name
        d.mkdir(parents=True)
        if with_image:
            (d / f"{name}_dseg.nii.gz").touch()
        if with_labels:
            (d / f"{name}_labels.tsv").touch()
        return d


class AvailableBundledAtlasesTests(BundledAtlasFixture):
    def test_returns_empty_list_when_data_dir_missing(self):
        self.assertEqual(available_bundled_atlases(), [])

    def test_lists_only_complete_atlas_directories_sorted(self):
        self.atlas_dir.mkdir()
        self._make_atlas_dir("chimera-b")
        self._make_atlas_dir("chimera-a")
        self._make_atlas_dir("incomplete-missing-labels", with_labels=False)
        (self.atlas_dir / "README.md").touch()  # not a directory -- ignored
        self.assertEqual(available_bundled_atlases(), ["chimera-a", "chimera-b"])


class FindBundledAtlasTests(BundledAtlasFixture):
    def test_returns_none_when_data_dir_missing(self):
        self.assertIsNone(_find_bundled_atlas("chimera-lfmihifis_scale3"))

    def test_finds_matching_directory_by_normalized_key(self):
        self.atlas_dir.mkdir()
        d = self._make_atlas_dir("chimera-LFMIHIFIS_scale3")
        # Query uses a different (but key-equivalent) form: lowercase, bare
        # number instead of "_scaleN" -- both normalize to the same _atlas_key.
        image_path, labels_path, label = _find_bundled_atlas("chimera-lfmihifis-3")
        self.assertEqual(image_path, d / "chimera-LFMIHIFIS_scale3_dseg.nii.gz")
        self.assertEqual(labels_path, d / "chimera-LFMIHIFIS_scale3_labels.tsv")
        self.assertEqual(label, "chimeraLFMIHIFIS_scale3")

    def test_bundled_colon_prefix_is_stripped_before_matching(self):
        self.atlas_dir.mkdir()
        self._make_atlas_dir("chimera-LFMIHIFIS_scale3")
        self.assertIsNotNone(_find_bundled_atlas("bundled:chimera-LFMIHIFIS_scale3"))

    def test_returns_none_when_no_directory_matches(self):
        self.atlas_dir.mkdir()
        self._make_atlas_dir("chimera-LFMIHIFIS_scale3")
        self.assertIsNone(_find_bundled_atlas("chimera-other_scale9"))

    def test_directory_missing_labels_is_skipped(self):
        self.atlas_dir.mkdir()
        self._make_atlas_dir("chimera-LFMIHIFIS_scale3", with_labels=False)
        self.assertIsNone(_find_bundled_atlas("chimera-LFMIHIFIS_scale3"))

    def test_directory_missing_image_is_skipped(self):
        self.atlas_dir.mkdir()
        self._make_atlas_dir("chimera-LFMIHIFIS_scale3", with_image=False)
        self.assertIsNone(_find_bundled_atlas("chimera-LFMIHIFIS_scale3"))


class LoadMniAtlasCustomAndErrorTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        patcher = patch("mrsiprep.parcellation.atlas_registry._find_bundled_atlas", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_custom_atlas_returns_configured_paths(self):
        config = SimpleNamespace(atlas="custom", custom_atlas=Path("/a/atlas.nii.gz"), custom_atlas_lut=Path("/a/labels.tsv"))
        result = load_mni_atlas(config, self.tmp)
        self.assertEqual(result, (Path("/a/atlas.nii.gz"), Path("/a/labels.tsv"), "custom"))

    def test_custom_atlas_without_lut_raises(self):
        config = SimpleNamespace(atlas="custom", custom_atlas=Path("/a/atlas.nii.gz"), custom_atlas_lut=None)
        with self.assertRaisesRegex(ValueError, "--custom-atlas and --custom-atlas-lut are required"):
            load_mni_atlas(config, self.tmp)

    def test_unsupported_atlas_raises(self):
        config = SimpleNamespace(atlas="bogus-atlas", custom_atlas=None, custom_atlas_lut=None)
        with self.assertRaisesRegex(ValueError, "Unsupported MNI atlas"):
            load_mni_atlas(config, self.tmp)

    def test_bundled_atlas_takes_priority_over_every_other_branch(self):
        with patch(
            "mrsiprep.parcellation.atlas_registry._find_bundled_atlas", return_value=(Path("a"), Path("b"), "bundled-name")
        ):
            config = SimpleNamespace(atlas="schaefer100", custom_atlas=None, custom_atlas_lut=None)
            result = load_mni_atlas(config, self.tmp)
        self.assertEqual(result, (Path("a"), Path("b"), "bundled-name"))


class LoadMniAtlasSchaeferFetchTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.config = SimpleNamespace(atlas="schaefer100", custom_atlas=None, custom_atlas_lut=None)
        patcher = patch("mrsiprep.parcellation.atlas_registry._find_bundled_atlas", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fetches_resamples_and_caches_when_not_already_present(self):
        atlas_img = nib.Nifti1Image(np.array([[[0, 1], [2, 3]]], dtype=np.int16), np.eye(4))
        fetched = SimpleNamespace(maps="fake_maps", labels=[b"7Networks_1", b"7Networks_2", b"7Networks_3"])

        with patch("nilearn.datasets.fetch_atlas_schaefer_2018", return_value=fetched) as fetch_mock, patch(
            "nilearn.datasets.load_mni152_template", return_value="mni_template"
        ), patch("nilearn.image.resample_to_img", return_value=atlas_img) as resample_mock, patch(
            "mrsiprep.parcellation.atlas_registry.write_labels"
        ) as write_labels_mock:
            atlas_path, labels_path, atlas_name = load_mni_atlas(self.config, self.tmp)

        fetch_mock.assert_called_once_with(n_rois=100, yeo_networks=7, resolution_mm=1)
        resample_mock.assert_called_once_with("fake_maps", "mni_template", interpolation="nearest", force_resample=True)
        self.assertEqual(atlas_name, "schaefer100")
        self.assertTrue(atlas_path.exists())
        write_labels_mock.assert_called_once_with(
            unittest.mock.ANY, ["7Networks_1", "7Networks_2", "7Networks_3"], labels_path
        )
        np.testing.assert_array_equal(write_labels_mock.call_args[0][0], [1, 2, 3])

    def test_reuses_cache_when_both_files_already_exist(self):
        atlas_path = self.tmp / "atlas-schaefer100_space-MNI152NLin2009cAsym_dseg.nii.gz"
        labels_path = self.tmp / "atlas-schaefer100_labels.tsv"
        atlas_path.touch()
        labels_path.touch()

        with patch("nilearn.datasets.fetch_atlas_schaefer_2018") as fetch_mock:
            result = load_mni_atlas(self.config, self.tmp)

        fetch_mock.assert_not_called()
        self.assertEqual(result, (atlas_path, labels_path, "schaefer100"))


class LoadMniAtlasMistFetchTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        patcher = patch("mrsiprep.parcellation.atlas_registry._find_bundled_atlas", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fetches_resamples_and_caches_when_not_already_present(self):
        atlas_img = nib.Nifti1Image(np.array([[[0, 5], [7, 7]]], dtype=np.int16), np.eye(4))
        fetched = SimpleNamespace(scale197="fake_scale197")
        config = SimpleNamespace(atlas="mist197", custom_atlas=None, custom_atlas_lut=None)

        with patch("nilearn.datasets.fetch_atlas_basc_multiscale_2015", return_value=fetched) as fetch_mock, patch(
            "nilearn.datasets.load_mni152_template", return_value="mni_template"
        ), patch("nilearn.image.resample_to_img", return_value=atlas_img), patch(
            "mrsiprep.parcellation.atlas_registry.write_labels"
        ) as write_labels_mock:
            _atlas_path, _labels_path, atlas_name = load_mni_atlas(config, self.tmp)

        fetch_mock.assert_called_once_with()
        self.assertEqual(atlas_name, "mist197")
        indices_arg, labels_arg, _labels_path_arg = write_labels_mock.call_args[0]
        np.testing.assert_array_equal(indices_arg, [5, 7])
        self.assertEqual(labels_arg, ["MIST-5", "MIST-7"])

    def test_hyphenated_alias_also_matches_and_reuses_cache(self):
        config = SimpleNamespace(atlas="mist-197", custom_atlas=None, custom_atlas_lut=None)
        atlas_path = self.tmp / "atlas-mist197_space-MNI152NLin2009cAsym_dseg.nii.gz"
        labels_path = self.tmp / "atlas-mist197_labels.tsv"
        atlas_path.touch()
        labels_path.touch()

        with patch("nilearn.datasets.fetch_atlas_basc_multiscale_2015") as fetch_mock:
            result = load_mni_atlas(config, self.tmp)

        fetch_mock.assert_not_called()
        self.assertEqual(result, (atlas_path, labels_path, "mist197"))


if __name__ == "__main__":
    unittest.main()
