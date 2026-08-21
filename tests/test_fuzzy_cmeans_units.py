import unittest

import numpy as np

from mrsiprep.tissue.fuzzy_cmeans import _fit_fcm, _merge_clusters_to_tissue, fuzzy_cmeans_segment


class FuzzyCmeansSegmentValidationTests(unittest.TestCase):
    def test_rejects_fewer_than_three_clusters(self):
        with self.assertRaisesRegex(ValueError, "n_clusters must be >= 3"):
            fuzzy_cmeans_segment(np.ones((4, 4, 4)), np.ones((4, 4, 4), dtype=bool), n_clusters=2)

    def test_rejects_mismatched_shapes(self):
        with self.assertRaisesRegex(ValueError, "does not match brain_mask shape"):
            fuzzy_cmeans_segment(np.ones((4, 4, 4)), np.ones((3, 3, 3), dtype=bool))

    def test_rejects_too_few_brain_voxels_for_cluster_count(self):
        t1 = np.ones((4, 4, 4))
        mask = np.zeros((4, 4, 4), dtype=bool)
        mask[0, 0, 0] = True
        mask[0, 0, 1] = True  # only 2 voxels, need >= 3 for n_clusters=3
        with self.assertRaisesRegex(ValueError, "cannot segment"):
            fuzzy_cmeans_segment(t1, mask, n_clusters=3)


class FuzzyCmeansSegmentOutputShapeTests(unittest.TestCase):
    def test_non_brain_voxels_are_zero_and_shape_matches_input(self):
        rng = np.random.default_rng(0)
        t1 = rng.random((6, 6, 6))
        mask = np.zeros((6, 6, 6), dtype=bool)
        mask[1:5, 1:5, 1:5] = True
        result = fuzzy_cmeans_segment(t1, mask, n_clusters=3, max_iter=20)
        for label in ("CSF", "GM", "WM"):
            self.assertEqual(result[label].shape, t1.shape)
            self.assertTrue(np.all(result[label][~mask] == 0.0))

    def test_squeezes_a_singleton_leading_axis(self):
        rng = np.random.default_rng(1)
        t1 = rng.random((1, 6, 6, 6))
        mask = np.ones((6, 6, 6), dtype=bool)
        # Must not raise despite the extra leading axis on t1_data alone.
        result = fuzzy_cmeans_segment(t1, mask, n_clusters=3, max_iter=10)
        self.assertEqual(result["GM"].shape, (6, 6, 6))


class FitFcmTests(unittest.TestCase):
    def test_memberships_sum_to_one_per_voxel(self):
        rng = np.random.default_rng(2)
        x = np.concatenate([rng.normal(0, 0.1, 30), rng.normal(5, 0.1, 30), rng.normal(10, 0.1, 30)])
        _centroids, memberships = _fit_fcm(x, n_clusters=3, m=2.0, max_iter=100, tol=1e-6, seed=0)
        np.testing.assert_allclose(memberships.sum(axis=1), 1.0, atol=1e-8)

    def test_centroids_returned_in_ascending_order(self):
        rng = np.random.default_rng(3)
        x = np.concatenate([rng.normal(10, 0.1, 30), rng.normal(0, 0.1, 30), rng.normal(5, 0.1, 30)])
        centroids, _memberships = _fit_fcm(x, n_clusters=3, m=2.0, max_iter=100, tol=1e-6, seed=0)
        self.assertTrue(np.all(np.diff(centroids) > 0))

    def test_recovers_well_separated_cluster_centers(self):
        rng = np.random.default_rng(4)
        x = np.concatenate([rng.normal(0, 0.05, 50), rng.normal(10, 0.05, 50), rng.normal(20, 0.05, 50)])
        centroids, _memberships = _fit_fcm(x, n_clusters=3, m=2.0, max_iter=200, tol=1e-8, seed=0)
        np.testing.assert_allclose(centroids, [0, 10, 20], atol=1.0)


class MergeClustersToTissueTests(unittest.TestCase):
    def test_three_clusters_map_directly_to_csf_gm_wm_by_intensity_order(self):
        centroids = np.array([1.0, 5.0, 9.0])
        memberships = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        tissue = _merge_clusters_to_tissue(centroids, memberships)
        np.testing.assert_array_equal(tissue["CSF"], [1.0, 0.0, 0.0])
        np.testing.assert_array_equal(tissue["GM"], [0.0, 1.0, 0.0])
        np.testing.assert_array_equal(tissue["WM"], [0.0, 0.0, 1.0])

    def test_overclustering_assigns_each_cluster_to_its_nearest_archetype(self):
        # 5 clusters spanning 0-20: archetypes are darkest(0), median(10),
        # brightest(20). Cluster at 3 should join CSF (nearer 0 than 10),
        # not be blindly bucketed into the middle (GM) class.
        centroids = np.array([0.0, 3.0, 10.0, 17.0, 20.0])
        memberships = np.eye(5)
        tissue = _merge_clusters_to_tissue(centroids, memberships)
        self.assertEqual(tissue["CSF"][0], 1.0)
        self.assertEqual(tissue["CSF"][1], 1.0)  # cluster at 3.0 joins CSF, not GM
        self.assertEqual(tissue["GM"][2], 1.0)
        self.assertEqual(tissue["WM"][3], 1.0)
        self.assertEqual(tissue["WM"][4], 1.0)

    def test_memberships_for_each_cluster_are_fully_conserved_into_one_tissue(self):
        centroids = np.array([0.0, 10.0, 20.0])
        memberships = np.array([[0.5, 0.3, 0.2]])
        tissue = _merge_clusters_to_tissue(centroids, memberships)
        total = tissue["CSF"][0] + tissue["GM"][0] + tissue["WM"][0]
        self.assertAlmostEqual(total, 1.0)


if __name__ == "__main__":
    unittest.main()
