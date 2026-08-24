import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np

from mrsiprep.reports.ventricle_overview import (
    MAX_MONTAGE_COLUMNS,
    _consensus_slice,
    _estimate_wm_mask,
    _tissue_priors,
    _prior_slice_bias,
    _slice_counts,
    _fsl_standard_path,
    _load_canonical,
    _mni_brain_mask,
    _lateral_ventricle_prior,
    _render_ventricle_montage,
    _world_bbox_center_and_extent,
    build_ventricle_qc_sections,
)


class FslStandardPathTests(unittest.TestCase):
    def test_returns_none_when_fsldir_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(_fsl_standard_path(Path("data/standard/thing.nii.gz")))

    def test_returns_none_when_file_missing_under_fsldir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"FSLDIR": tmpdir}, clear=True):
                self.assertIsNone(_fsl_standard_path(Path("data/standard/missing.nii.gz")))

    def test_returns_resolved_path_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relative = Path("data/standard/thing.nii.gz")
            full = Path(tmpdir) / relative
            full.parent.mkdir(parents=True)
            full.touch()
            with patch.dict("os.environ", {"FSLDIR": tmpdir}, clear=True):
                self.assertEqual(_fsl_standard_path(relative), full)


class LoadCanonicalTests(unittest.TestCase):
    def test_loads_3d_volume_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "vol.nii.gz"
            data = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            loaded, affine = _load_canonical(path)
        self.assertEqual(loaded.shape, (2, 3, 4))
        np.testing.assert_allclose(affine, np.eye(4))

    def test_squeezes_4d_volume_to_first_frame(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "vol4d.nii.gz"
            data = np.stack([np.ones((2, 3, 4)), np.full((2, 3, 4), 9.0)], axis=-1).astype(np.float32)
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            loaded, _ = _load_canonical(path)
        self.assertEqual(loaded.shape, (2, 3, 4))
        np.testing.assert_allclose(loaded, np.ones((2, 3, 4)))


class WorldBboxCenterAndExtentTests(unittest.TestCase):
    def test_identity_affine_matches_voxel_bbox(self):
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[2:5, 3:6, 4:7] = True  # occupies indices 2-4, 3-5, 4-6
        center, extent = _world_bbox_center_and_extent(mask, np.eye(4))
        np.testing.assert_allclose(center, [3.0, 4.0, 5.0])
        np.testing.assert_allclose(extent, [2.0, 2.0, 2.0])

    def test_scaled_affine_scales_the_extent(self):
        mask = np.zeros((10, 10, 10), dtype=bool)
        mask[0:2, 0:2, 0:2] = True
        affine = np.diag([2.0, 2.0, 2.0, 1.0])
        _, extent = _world_bbox_center_and_extent(mask, affine)
        np.testing.assert_allclose(extent, [2.0, 2.0, 2.0])  # 1 voxel of span * scale 2


def _flat_bias(n_slices):
    """Neutral bias, for tests isolating the voting rule from the prior."""
    return np.ones(n_slices, dtype=float)


class ConsensusSliceTests(unittest.TestCase):
    def test_returns_slice_index_with_most_detected_voxels(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[:, :, 2] = True  # every voxel in slice z=2
        counts = [_slice_counts(detected)]
        self.assertEqual(_consensus_slice(counts, [_flat_bias(4)], min_voxels=3), 2)

    def test_returns_none_when_below_minimum(self):
        detected = np.zeros((5, 5, 4), dtype=bool)
        detected[0, 0, 1] = True  # only 1 voxel anywhere
        counts = [_slice_counts(detected)]
        self.assertIsNone(_consensus_slice(counts, [_flat_bias(4)], min_voxels=3))

    def test_returns_none_for_no_metabolites(self):
        self.assertIsNone(_consensus_slice([], []))

    def test_majority_outvotes_a_single_dissenting_metabolite(self):
        """The reported bug: one noisy map landed on its own slice and the
        montage rendered each metabolite somewhere different."""
        agree_a = np.zeros(12, dtype=float); agree_a[7] = 10.0
        agree_b = np.zeros(12, dtype=float); agree_b[7] = 8.0
        dissent = np.zeros(12, dtype=float); dissent[2] = 40.0  # loudest in absolute terms
        bias = [_flat_bias(12)] * 3
        self.assertEqual(_consensus_slice([agree_a, agree_b, dissent], bias, min_voxels=3), 7)

    def test_a_single_high_snr_metabolite_cannot_dominate(self):
        # Per-metabolite peak normalisation is what makes this hold: without
        # it the 500-voxel map would win on raw magnitude alone.
        loud = np.zeros(10, dtype=float); loud[1] = 500.0
        quiet_a = np.zeros(10, dtype=float); quiet_a[6] = 4.0
        quiet_b = np.zeros(10, dtype=float); quiet_b[6] = 5.0
        bias = [_flat_bias(10)] * 3
        self.assertEqual(_consensus_slice([loud, quiet_a, quiet_b], bias, min_voxels=3), 6)

    def test_bias_cannot_manufacture_a_detection(self):
        # min_voxels is checked against raw counts, so a strong bias at a
        # slice with almost nothing detected must still return None.
        counts = [np.array([0.0, 1.0, 0.0, 0.0])]
        bias = [np.array([0.0, 100.0, 0.0, 0.0])]
        self.assertIsNone(_consensus_slice(counts, bias, min_voxels=3))


def _img_like(value, shape=(2, 2, 2)):
    import nibabel as nib

    return nib.Nifti1Image(np.full(shape, value, dtype=np.float32), np.eye(4))


class TissuePriorsTests(unittest.TestCase):
    def test_prefers_the_reference_template(self):
        gm = _img_like(0.8)
        wm = _img_like(0.2)
        with patch("mrsiprep.config.templates.template_tissue_probseg", side_effect=[gm, wm]):
            result = _tissue_priors()
        self.assertIsNotNone(result)
        gm_data, wm_data, _ = result
        self.assertAlmostEqual(float(gm_data.max()), 0.8, places=5)
        self.assertAlmostEqual(float(wm_data.max()), 0.2, places=5)

    def test_falls_back_to_fsl_and_rescales_to_0_1(self):
        # FSL ships these as 0-255 in a different template lineage, so the
        # fallback must rescale or every probability comparison is nonsense.
        from mrsiprep.config.templates import TemplateError

        with patch("mrsiprep.config.templates.template_tissue_probseg", side_effect=TemplateError("nope")), patch(
            "mrsiprep.reports.ventricle_overview._fsl_standard_path", side_effect=[Path("/gm.hdr"), Path("/wm.hdr")]
        ), patch(
            "mrsiprep.reports.ventricle_overview._load_canonical",
            side_effect=[(np.full((2, 2, 2), 255.0), np.eye(4)), (np.full((2, 2, 2), 51.0), np.eye(4))],
        ):
            gm_data, wm_data, _ = _tissue_priors()
        self.assertAlmostEqual(float(gm_data.max()), 1.0, places=5)
        self.assertAlmostEqual(float(wm_data.max()), 0.2, places=5)

    def test_none_when_neither_source_is_available(self):
        from mrsiprep.config.templates import TemplateError

        with patch("mrsiprep.config.templates.template_tissue_probseg", side_effect=TemplateError("nope")), patch(
            "mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=None
        ):
            self.assertIsNone(_tissue_priors())


class EstimateWmMaskTests(unittest.TestCase):
    """The GM/WM row's data-driven step: the prior only says which side is
    which, the split itself comes from the metabolite's own signal."""

    def _priors(self, shape=(6, 6, 4)):
        gm = np.zeros(shape, dtype=float); gm[:3] = 1.0
        wm = np.zeros(shape, dtype=float); wm[3:] = 1.0
        brain = np.ones(shape, dtype=bool)
        return gm, wm, brain

    def test_recovers_the_split_when_wm_is_brighter(self):
        gm, wm, brain = self._priors()
        signal = np.zeros((6, 6, 4), dtype=float)
        signal[:3] = 10.0   # GM
        signal[3:] = 30.0   # WM
        wm_mask, contrast = _estimate_wm_mask(signal, gm, wm, brain)
        self.assertTrue(wm_mask[3:].all())
        self.assertFalse(wm_mask[:3].any())
        self.assertAlmostEqual(contrast, 100.0, places=5)  # |30-10| / 20

    def test_polarity_is_measured_not_assumed(self):
        """Ins runs higher in grey matter, NAA/Cho higher in white; a fixed
        'WM is brighter' rule would invert the outline for half the panel."""
        gm, wm, brain = self._priors()
        signal = np.zeros((6, 6, 4), dtype=float)
        signal[:3] = 30.0   # GM brighter this time
        signal[3:] = 10.0
        wm_mask, _ = _estimate_wm_mask(signal, gm, wm, brain)
        self.assertTrue(wm_mask[3:].all())
        self.assertFalse(wm_mask[:3].any())

    def test_no_contrast_reports_near_zero(self):
        gm, wm, brain = self._priors()
        signal = np.full((6, 6, 4), 20.0)
        _, contrast = _estimate_wm_mask(signal, gm, wm, brain)
        self.assertAlmostEqual(contrast, 0.0, places=6)

    def test_returns_none_when_a_prior_core_is_too_small(self):
        shape = (6, 6, 4)
        gm = np.ones(shape, dtype=float)
        wm = np.zeros(shape, dtype=float)  # no WM core at all
        brain = np.ones(shape, dtype=bool)
        self.assertIsNone(_estimate_wm_mask(np.ones(shape), gm, wm, brain))

    def test_estimate_is_confined_to_the_brain_mask(self):
        gm, wm, _ = self._priors()
        signal = np.zeros((6, 6, 4), dtype=float)
        signal[:3] = 10.0
        signal[3:] = 30.0
        brain = np.zeros((6, 6, 4), dtype=bool)
        brain[:, :, :2] = True
        wm_mask, _ = _estimate_wm_mask(signal, gm, wm, brain)
        self.assertFalse(wm_mask[:, :, 2:].any())


class PriorSliceBiasTests(unittest.TestCase):
    def test_peaks_at_the_priors_centre_of_mass(self):
        prior = np.zeros((4, 4, 11), dtype=bool)
        prior[:, :, 8] = True
        self.assertEqual(int(np.argmax(_prior_slice_bias(prior))), 8)

    def test_falls_back_to_the_array_middle_for_an_empty_prior(self):
        prior = np.zeros((4, 4, 11), dtype=bool)
        self.assertEqual(int(np.argmax(_prior_slice_bias(prior))), 5)

    def test_downweights_slices_far_from_the_prior(self):
        """Why the inferior-slice false positives went away: those slices
        are many sigma from where the prior puts the ventricles."""
        prior = np.zeros((4, 4, 20), dtype=bool)
        prior[:, :, 11] = True
        bias = _prior_slice_bias(prior)
        self.assertGreater(bias[11], bias[6])
        self.assertGreater(bias[10], bias[2])


class LateralVentriclePriorTests(unittest.TestCase):
    def test_none_when_atlas_unavailable(self):
        with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=None):
            self.assertIsNone(_lateral_ventricle_prior())

    def test_combines_left_and_right_ventricle_channels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            atlas_path = Path(tmpdir) / "atlas.nii.gz"
            data = np.zeros((4, 4, 4, 21), dtype=np.float32)
            data[1, 1, 1, 2] = 60.0  # left lateral ventricle channel
            data[1, 1, 1, 13] = 70.0  # right lateral ventricle channel -- combined should clip to 100
            nib.save(nib.Nifti1Image(data, np.eye(4)), atlas_path)
            with patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=atlas_path):
                combined, affine = _lateral_ventricle_prior()
        self.assertEqual(combined[1, 1, 1], 100.0)  # 60 + 70 clipped to 100
        self.assertEqual(combined[0, 0, 0], 0.0)


class MniBrainMaskTests(unittest.TestCase):
    """The mask now comes from the run's reference template, with FSL's copy
    kept only as a fallback -- FSL ships the MNI152NLin6Asym lineage, so it
    describes a different space than the data being checked."""

    def _mask_img(self):
        data = np.array([[[0.0, 1.0], [0.5, 0.0]]], dtype=np.float32)
        return nib.Nifti1Image(data, np.eye(4))

    def test_prefers_the_reference_template(self):
        with patch(
            "mrsiprep.config.templates.template_brain_mask", return_value=self._mask_img()
        ), patch("mrsiprep.reports.ventricle_overview._fsl_standard_path") as fsl:
            mask, _ = _mni_brain_mask()
        fsl.assert_not_called()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[0, 0, 1])
        self.assertFalse(mask[0, 0, 0])

    def test_falls_back_to_fsl_when_the_template_is_unavailable(self):
        from mrsiprep.config.templates import TemplateError

        with tempfile.TemporaryDirectory() as tmpdir:
            mask_path = Path(tmpdir) / "mask.nii.gz"
            nib.save(self._mask_img(), mask_path)
            with patch(
                "mrsiprep.config.templates.template_brain_mask",
                side_effect=TemplateError("no cache"),
            ), patch(
                "mrsiprep.reports.ventricle_overview._fsl_standard_path",
                return_value=mask_path,
            ):
                mask, _ = _mni_brain_mask()
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask[0, 0, 1])

    def test_none_when_neither_source_is_available(self):
        from mrsiprep.config.templates import TemplateError

        with patch(
            "mrsiprep.config.templates.template_brain_mask", side_effect=TemplateError("no cache")
        ), patch("mrsiprep.reports.ventricle_overview._fsl_standard_path", return_value=None):
            self.assertIsNone(_mni_brain_mask())


class RenderVentricleMontageTests(unittest.TestCase):
    def test_wraps_rows_beyond_max_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            n_metabolites = MAX_MONTAGE_COLUMNS + 2  # forces a second row
            panels = []
            for i in range(n_metabolites):
                signal = np.ones((4, 4, 3), dtype=np.float32)
                prior_roi = np.zeros((4, 4, 3), dtype=bool)
                detected = np.zeros((4, 4, 3), dtype=bool)
                panels.append((f"MET{i}", signal, prior_roi, detected))
            result = _render_ventricle_montage(panels, 1, out_path)
            self.assertEqual(result, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

    def test_tissue_band_adds_a_second_set_of_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            panels, tissue = [], {}
            for i in range(3):
                signal = np.ones((4, 4, 3), dtype=np.float32)
                blank = np.zeros((4, 4, 3), dtype=bool)
                panels.append((f"MET{i}", signal, blank, blank))
                tissue[f"MET{i}"] = (blank, 12.5)
            result = _render_ventricle_montage(panels, 1, out_path, tissue)
            self.assertEqual(result, out_path)
            self.assertGreater(out_path.stat().st_size, 0)

    def test_metabolite_without_a_tissue_estimate_keeps_its_column(self):
        """Columns must stay aligned between the two bands, so a metabolite
        with no usable estimate gets an empty panel rather than shifting the
        rest of the row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "montage.png"
            signal = np.ones((4, 4, 3), dtype=np.float32)
            blank = np.zeros((4, 4, 3), dtype=bool)
            panels = [("HasTissue", signal, blank, blank), ("NoTissue", signal, blank, blank)]
            tissue = {"HasTissue": (blank, 8.0)}
            _render_ventricle_montage(panels, 1, out_path, tissue)
            self.assertGreater(out_path.stat().st_size, 0)


class BuildVentricleQcSectionsTests(unittest.TestCase):
    def test_returns_empty_when_prior_unavailable(self):
        config = SimpleNamespace(derivative_dir=Path("/tmp/deriv"))
        with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=None), patch(
            "mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.zeros((2, 2, 2), dtype=bool), np.eye(4))
        ):
            self.assertEqual(build_ventricle_qc_sections(config, "01", "01", {}), [])

    def test_returns_empty_when_mni_brain_mask_unavailable(self):
        config = SimpleNamespace(derivative_dir=Path("/tmp/deriv"))
        with patch(
            "mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros((2, 2, 2)), np.eye(4))
        ), patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=None):
            self.assertEqual(build_ventricle_qc_sections(config, "01", "01", {}), [])

    def test_skips_metabolites_without_a_placement_but_keeps_undetected_ones(self):
        """Placement failure still drops a metabolite -- there is no sensible
        slice to draw it at. A metabolite with a valid placement but no
        detected ventricle voxels is now *kept* and drawn at the shared
        slice: an empty red contour is the informative result, and dropping
        it would leave the montage comparing different metabolite sets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(derivative_dir=Path(tmpdir) / "derivatives" / "mrsiprep")
            # sorted(raw_maps) iterates as ["Good", "NoDetection", "NoPlacement"];
            # the side_effect list below is keyed to that exact order.
            raw_maps = {"NoPlacement": Path("a.nii.gz"), "NoDetection": Path("b.nii.gz"), "Good": Path("c.nii.gz")}
            fake_signal = np.ones((4, 4, 3), dtype=np.float32)
            valid_placement = ("c", "c", np.array([1.0, 1.0, 1.0]))
            good = np.zeros((4, 4, 3), dtype=bool)
            good[:, :, 1] = True
            empty = np.zeros((4, 4, 3), dtype=bool)

            with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros((4, 4, 3)), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.ones((4, 4, 3), dtype=bool), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._load_canonical", side_effect=lambda p: (fake_signal, np.eye(4))), \
                patch(
                    "mrsiprep.reports.ventricle_overview._mni_to_native_affine",
                    # Good -> valid; NoDetection -> valid; NoPlacement -> None.
                    side_effect=[valid_placement, valid_placement, None],
                ), \
                patch("mrsiprep.reports.ventricle_overview._tissue_priors", return_value=None), \
                patch("mrsiprep.reports.ventricle_overview._warp_prior_to_native", return_value=np.ones((4, 4, 3), dtype=bool)), \
                patch("mrsiprep.reports.ventricle_overview._detect_ventricle_mask", side_effect=[good, empty]), \
                patch("mrsiprep.reports.ventricle_overview._render_ventricle_montage", return_value=Path(tmpdir) / "out.png") as render:
                sections = build_ventricle_qc_sections(config, "01", "01", raw_maps)

        rendered_panels, rendered_z, _, rendered_tissue = render.call_args[0]
        self.assertIsNone(rendered_tissue)  # _tissue_priors patched to None above
        self.assertEqual([p[0] for p in rendered_panels], ["Good", "NoDetection"])
        self.assertEqual(rendered_z, 1)
        self.assertEqual(len(sections), 1)
        title, body = sections[0]
        self.assertIn("Ventricle visibility", title)
        self.assertIn("z=1", body)
        self.assertIn("<img", body)

    def test_tissue_band_is_built_and_described_when_priors_are_available(self):
        """End-to-end for the GM/WM row: the prior is warped by the same
        placement as the ventricles, the split comes from the signal, and the
        montage gets a tissue dict keyed by metabolite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(derivative_dir=Path(tmpdir) / "derivatives" / "mrsiprep")
            shape = (6, 6, 4)
            signal = np.zeros(shape, dtype=np.float32)
            signal[:3] = 10.0   # GM side
            signal[3:] = 30.0   # WM side
            detected = np.zeros(shape, dtype=bool)
            detected[:, :, 1] = True
            gm_mni = np.zeros(shape, dtype=float); gm_mni[:3] = 1.0
            wm_mni = np.zeros(shape, dtype=float); wm_mni[3:] = 1.0

            with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros(shape), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.ones(shape, dtype=bool), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._tissue_priors", return_value=(gm_mni, wm_mni, np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._load_canonical", side_effect=lambda p: (signal, np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_to_native_affine",
                      return_value=(np.zeros(3), np.zeros(3), np.ones(3))), \
                patch("mrsiprep.reports.ventricle_overview._warp_prior_to_native", return_value=np.ones(shape, dtype=bool)), \
                patch("mrsiprep.reports.ventricle_overview._detect_ventricle_mask", return_value=detected), \
                patch("mrsiprep.reports.ventricle_overview._render_ventricle_montage", return_value=Path(tmpdir) / "o.png") as render:
                sections = build_ventricle_qc_sections(config, "01", "01", {"CrPCr": Path("c.nii.gz")})

        _, _, _, rendered_tissue = render.call_args[0]
        self.assertIn("CrPCr", rendered_tissue)
        wm_mask, contrast = rendered_tissue["CrPCr"]
        self.assertTrue(wm_mask[3:].all())          # brighter side recovered as WM
        self.assertFalse(wm_mask[:3].any())
        self.assertAlmostEqual(contrast, 100.0, places=4)
        title, body = sections[0]
        self.assertIn("GM/WM", title)
        self.assertIn("continuity", body)

    def test_returns_empty_when_no_metabolite_yields_a_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SimpleNamespace(derivative_dir=Path(tmpdir) / "derivatives" / "mrsiprep")
            fake_signal = np.ones((4, 4, 3), dtype=np.float32)
            valid_placement = ("c", "c", np.array([1.0, 1.0, 1.0]))
            with patch("mrsiprep.reports.ventricle_overview._lateral_ventricle_prior", return_value=(np.zeros((4, 4, 3)), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_brain_mask", return_value=(np.ones((4, 4, 3), dtype=bool), np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._load_canonical", side_effect=lambda p: (fake_signal, np.eye(4))), \
                patch("mrsiprep.reports.ventricle_overview._mni_to_native_affine", return_value=valid_placement), \
                patch("mrsiprep.reports.ventricle_overview._tissue_priors", return_value=None), \
                patch("mrsiprep.reports.ventricle_overview._warp_prior_to_native", return_value=np.ones((4, 4, 3), dtype=bool)), \
                patch("mrsiprep.reports.ventricle_overview._detect_ventricle_mask", return_value=np.zeros((4, 4, 3), dtype=bool)), \
                patch("mrsiprep.reports.ventricle_overview._render_ventricle_montage") as render:
                sections = build_ventricle_qc_sections(config, "01", "01", {"CrPCr": Path("c.nii.gz")})
        self.assertEqual(sections, [])
        render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
