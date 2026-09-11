import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.parcellation.cubic import generate_cubic_atlas, parse_cubic_atlas_name


class ParseCubicAtlasNameTests(unittest.TestCase):
    def test_matches_the_no_hyphen_form(self):
        self.assertEqual(parse_cubic_atlas_name("cubic10mm"), 10)

    def test_matches_the_hyphenated_form(self):
        self.assertEqual(parse_cubic_atlas_name("cubic-10mm"), 10)

    def test_matches_any_integer_size_not_just_10_or_15(self):
        self.assertEqual(parse_cubic_atlas_name("cubic12mm"), 12)

    def test_case_insensitive(self):
        self.assertEqual(parse_cubic_atlas_name("Cubic10MM".lower()), 10)

    def test_returns_none_for_unrelated_names(self):
        self.assertIsNone(parse_cubic_atlas_name("schaefer100"))
        self.assertIsNone(parse_cubic_atlas_name("cubic"))
        self.assertIsNone(parse_cubic_atlas_name("mist197"))


def _fake_gm_mask(shape=(20, 20, 20)):
    """A synthetic mask: a solid block leaving a margin of empty voxels on
    every side, so bounding-box-anchoring behavior is actually exercised."""
    mask = np.zeros(shape, dtype=np.uint8)
    mask[5:15, 4:16, 3:17] = 1
    return nib.Nifti1Image(mask, np.eye(4))


class GenerateCubicAtlasTests(unittest.TestCase):
    def test_raises_for_a_non_positive_cube_size(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            generate_cubic_atlas(0)
        with self.assertRaisesRegex(ValueError, "positive"):
            generate_cubic_atlas(-5)

    def test_raises_when_the_mask_is_empty(self):
        empty = nib.Nifti1Image(np.zeros((10, 10, 10), dtype=np.uint8), np.eye(4))
        with patch("nibabel.load", return_value=empty):
            with self.assertRaisesRegex(ValueError, "empty"):
                generate_cubic_atlas(10)

    def test_labels_only_voxels_inside_the_mask(self):
        with patch("nibabel.load", return_value=_fake_gm_mask()):
            out = generate_cubic_atlas(5)
        data = np.asanyarray(out.dataobj)
        mask = np.asanyarray(_fake_gm_mask().dataobj) != 0
        self.assertTrue(np.all(data[~mask] == 0))
        self.assertTrue(np.all(data[mask] != 0))

    def test_output_shares_the_mask_grid_and_affine(self):
        fake = _fake_gm_mask()
        with patch("nibabel.load", return_value=fake):
            out = generate_cubic_atlas(5)
        self.assertEqual(out.shape, fake.shape)
        np.testing.assert_array_equal(out.affine, fake.affine)

    def test_smaller_cubes_produce_more_labels_than_larger_ones(self):
        with patch("nibabel.load", return_value=_fake_gm_mask()):
            small = generate_cubic_atlas(3)
            large = generate_cubic_atlas(10)
        n_small = len(np.unique(np.asanyarray(small.dataobj))) - 1
        n_large = len(np.unique(np.asanyarray(large.dataobj))) - 1
        self.assertGreater(n_small, n_large)

    def test_a_cube_covering_the_whole_mask_yields_exactly_one_label(self):
        with patch("nibabel.load", return_value=_fake_gm_mask()):
            out = generate_cubic_atlas(50)
        data = np.asanyarray(out.dataobj)
        labels = np.unique(data)
        labels = labels[labels != 0]
        self.assertEqual(len(labels), 1)

    def test_labels_are_a_contiguous_range_starting_at_one(self):
        with patch("nibabel.load", return_value=_fake_gm_mask()):
            out = generate_cubic_atlas(4)
        data = np.asanyarray(out.dataobj)
        labels = sorted(int(v) for v in np.unique(data) if v != 0)
        self.assertEqual(labels, list(range(1, len(labels) + 1)))

    def test_same_cube_size_is_deterministic_across_calls(self):
        with patch("nibabel.load", return_value=_fake_gm_mask()):
            out1 = generate_cubic_atlas(5)
            out2 = generate_cubic_atlas(5)
        np.testing.assert_array_equal(np.asanyarray(out1.dataobj), np.asanyarray(out2.dataobj))

    def test_skips_blocks_that_fall_entirely_in_a_gap_between_two_mask_regions(self):
        # Two small blobs near opposite corners of the bounding box, with a
        # large empty gap between them along every axis -- most candidate
        # blocks across the bbox are entirely empty and must be skipped
        # (the xy-plane early-continue and the per-block continue both).
        shape = (30, 30, 30)
        mask = np.zeros(shape, dtype=np.uint8)
        mask[0:2, 0:2, 0:2] = 1
        mask[27:29, 27:29, 27:29] = 1
        fake = nib.Nifti1Image(mask, np.eye(4))
        with patch("nibabel.load", return_value=fake):
            out = generate_cubic_atlas(3)
        data = np.asanyarray(out.dataobj)
        labels = np.unique(data)
        labels = labels[labels != 0]
        # Exactly one label per blob -- each is smaller than one cube and
        # far from the other, so nothing merges and nothing spurious appears.
        self.assertEqual(len(labels), 2)
        self.assertTrue(np.all(data[mask == 0] == 0))

    def test_no_labelled_voxel_falls_outside_the_masks_own_bounding_box(self):
        fake = _fake_gm_mask()
        with patch("nibabel.load", return_value=fake):
            out = generate_cubic_atlas(5)
        data = np.asanyarray(out.dataobj)
        mask = np.asanyarray(fake.dataobj) != 0
        occupied = np.where(mask)
        for axis in range(3):
            self.assertGreaterEqual(np.where(data != 0)[axis].min(), occupied[axis].min())
            self.assertLessEqual(np.where(data != 0)[axis].max(), occupied[axis].max())


if __name__ == "__main__":
    unittest.main()
