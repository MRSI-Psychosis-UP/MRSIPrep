import unittest

import numpy as np

from mrsiprep.mrsi.filtering import get_spike_mask


def _base_volume(shape=(30, 30, 30), background=2.0, noise=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return background + rng.normal(0, noise, size=shape).astype(np.float32)


class GetSpikeMaskSizeCapTests(unittest.TestCase):
    def test_small_cluster_within_cap_is_kept(self):
        data = _base_volume()
        data[10:12, 10, 10] = 50.0  # 2-voxel cluster, well above cap
        mask = get_spike_mask(data, percentile=99.0, max_cluster_voxels=6, extreme_zscore=None)
        self.assertTrue(mask[10, 10, 10])
        self.assertTrue(mask[11, 10, 10])

    def test_large_benign_cluster_is_exempted_without_zscore_net(self):
        data = _base_volume()
        # A large, modest-intensity cluster (mean z well under 4) -- real
        # focal-signal-like, not an artifact.
        data[5:5 + 3, 5:5 + 3, 5:5 + 3] = 6.0  # 27 voxels, mild elevation
        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=6, extreme_zscore=None)
        self.assertFalse(mask[6, 6, 6], "large modest-intensity cluster should be exempted (size cap, no z-net)")


class GetSpikeMaskZscoreSafetyNetTests(unittest.TestCase):
    def test_extreme_large_cluster_is_rescued_by_zscore_net(self):
        """Regression test for the real sub-CHUVUP015 case: a large cluster
        (>cap) whose voxels are wildly implausible (mean z far above 4,
        typically a slab-edge acquisition artifact) must still be repaired
        even though it exceeds the cluster-size cap."""
        data = _base_volume()
        data[5:5 + 3, 5:5 + 3, 5:5 + 3] = 400.0  # 27-voxel cluster, extreme z
        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=6, extreme_zscore=4.0)
        self.assertTrue(mask[6, 6, 6], "extreme-intensity large cluster should be rescued by the z-score net")

    def test_large_benign_cluster_stays_exempted_with_zscore_net_on(self):
        """The z-score net must never pull in a cluster the size cap
        already exempted for good reason -- only extreme outliers."""
        data = _base_volume()
        data[5:5 + 3, 5:5 + 3, 5:5 + 3] = 6.0  # 27 voxels, mild elevation, low z
        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=6, extreme_zscore=4.0)
        self.assertFalse(mask[6, 6, 6], "modest-intensity large cluster should remain exempted despite the z-score net")

    def test_zscore_net_never_exempts_something_size_would_have_kept(self):
        data = _base_volume()
        data[10:12, 10, 10] = 50.0  # small cluster, within cap regardless of z-score
        mask = get_spike_mask(data, percentile=99.0, max_cluster_voxels=6, extreme_zscore=0.01)
        self.assertTrue(mask[10, 10, 10])
        self.assertTrue(mask[11, 10, 10])

    def test_disabling_zscore_net_restores_pure_size_based_exemption(self):
        data = _base_volume()
        data[5:5 + 3, 5:5 + 3, 5:5 + 3] = 400.0  # extreme, but net is off
        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=6, extreme_zscore=None)
        self.assertFalse(mask[6, 6, 6], "extreme_zscore=None should behave exactly like pure size-based exemption")


class GetSpikeMaskBrainMaskTests(unittest.TestCase):
    """mask= restricts both the percentile threshold and the resulting spike
    mask to a boundary region, matching mrsitoolbox.filters.biharmonic
    .BiHarmonic.get_spike_mask's bnd_np parameter (mrsiprep's earlier port
    never exposed it and always used the data>0 default)."""

    def test_outside_mask_signal_does_not_shift_threshold(self):
        data = _base_volume()
        brain = np.zeros_like(data, dtype=bool)
        brain[5:25, 5:25, 5:25] = True
        # Extreme "skull" signal entirely outside the brain mask: should not
        # pull the percentile threshold computed over brain voxels.
        data[0:5, 0:5, 0:5] = 500.0

        threshold_masked = get_spike_mask(data, percentile=99.0, max_cluster_voxels=None, mask=brain)
        threshold_unmasked = get_spike_mask(data, percentile=99.0, max_cluster_voxels=None, mask=None)
        # Unmasked run flags the outside-brain signal; masked run must not.
        self.assertTrue(threshold_unmasked[0, 0, 0])
        self.assertFalse(threshold_masked[0, 0, 0])

    def test_spike_mask_never_flags_voxels_outside_mask(self):
        data = _base_volume()
        brain = np.zeros_like(data, dtype=bool)
        brain[5:25, 5:25, 5:25] = True
        data[10, 10, 10] = 50.0  # real spike, inside brain
        data[0, 0, 0] = 50.0  # same value, but outside brain

        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=None, mask=brain)
        self.assertTrue(mask[10, 10, 10])
        self.assertFalse(mask[0, 0, 0], "mask= must exclude out-of-boundary voxels from the spike mask itself")

    def test_mask_none_preserves_original_data_greater_than_zero_default(self):
        """mrsitoolbox's own get_spike_mask defaults bnd_np to data>0 when no
        boundary is given -- mask=None must reproduce that exactly (this is
        the pre-existing, unmasked mrsiprep behavior)."""
        data = _base_volume()
        data[10, 10, 10] = 50.0
        via_none = get_spike_mask(data, percentile=90.0, max_cluster_voxels=None, mask=None)
        via_explicit_positive = get_spike_mask(data, percentile=90.0, max_cluster_voxels=None, mask=(data > 0))
        np.testing.assert_array_equal(via_none, via_explicit_positive)


class GetSpikeMaskEdgeCasesTests(unittest.TestCase):
    def test_no_positive_voxels_returns_empty_mask(self):
        data = np.zeros((10, 10, 10), dtype=np.float32)
        mask = get_spike_mask(data)
        self.assertFalse(mask.any())

    def test_max_cluster_voxels_none_disables_size_filtering_entirely(self):
        data = _base_volume()
        data[5:5 + 3, 5:5 + 3, 5:5 + 3] = 400.0  # large cluster
        mask = get_spike_mask(data, percentile=90.0, max_cluster_voxels=None)
        self.assertTrue(mask[6, 6, 6], "max_cluster_voxels=None should flag every above-threshold voxel")


if __name__ == "__main__":
    unittest.main()
