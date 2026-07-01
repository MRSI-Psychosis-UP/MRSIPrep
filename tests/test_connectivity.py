import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.connectivity.connectivity import (
    compute_metabolite_connectivity,
    parcellate_means,
    parcellate_zscored,
    perturb_metabolite_map,
)


def _save_volume(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data.astype("float32"), np.eye(4)), path)
    return path


class PerturbMetaboliteMapTests(unittest.TestCase):
    def test_stays_within_bounds_and_masked_outside_brain(self):
        rng = np.random.default_rng(0)
        signal = rng.uniform(1, 10, size=(4, 4, 4))
        crlb = rng.uniform(1, 20, size=(4, 4, 4))
        brainmask = np.ones((4, 4, 4))
        brainmask[0, 0, 0] = 0

        noisy = perturb_metabolite_map(signal, crlb, brainmask, sigma_scale=2.0, rng=rng)

        self.assertEqual(noisy[0, 0, 0], 0)
        self.assertTrue(np.all(noisy >= 0))
        self.assertTrue(np.all(noisy <= signal.mean() + 3 * signal.std()))

    def test_different_seeds_give_different_results(self):
        signal = np.full((4, 4, 4), 5.0)
        crlb = np.full((4, 4, 4), 10.0)
        brainmask = np.ones((4, 4, 4))

        a = perturb_metabolite_map(signal, crlb, brainmask, rng=np.random.default_rng(1))
        b = perturb_metabolite_map(signal, crlb, brainmask, rng=np.random.default_rng(2))

        self.assertFalse(np.allclose(a, b))


class ParcellateZscoredTests(unittest.TestCase):
    def test_known_parcel_means(self):
        atlas = np.zeros((4, 4, 4), dtype=int)
        atlas[:2, :, :] = 1
        atlas[2:, :, :] = 2

        met0 = np.zeros((4, 4, 4))
        met0[:2] = 1.0
        met0[2:] = 3.0
        perturbed_4d = np.stack([met0])

        result = parcellate_zscored(perturbed_4d, atlas, np.array([1, 2]))

        self.assertEqual(result.shape, (1, 2))
        self.assertLess(result[0, 0], result[0, 1])

    def test_nan_voxels_are_skipped_like_nanmean(self):
        atlas = np.zeros((4, 4, 4), dtype=int)
        atlas[:2, :, :] = 1
        atlas[2:, :, :] = 2

        met0 = np.full((4, 4, 4), 2.0)
        met0[0, 0, 0] = np.nan  # single NaN voxel inside parcel 1
        image_4d = np.stack([met0])

        result = parcellate_means(image_4d, atlas, np.array([1, 2]))

        # Parcel 1's mean should be computed over its remaining finite voxels (still 2.0),
        # not poisoned to NaN by the single NaN voxel, matching np.nanmean's behavior.
        self.assertAlmostEqual(result[0, 0], 2.0)
        self.assertAlmostEqual(result[0, 1], 2.0)

    def test_voxel_weights_bias_the_mean_toward_high_weight_voxels(self):
        atlas = np.ones((2, 2, 2), dtype=int)
        met0 = np.array([[[1.0, 1.0], [1.0, 1.0]], [[5.0, 5.0], [5.0, 5.0]]])
        image_4d = np.stack([met0])

        unweighted = parcellate_means(image_4d, atlas, np.array([1]))
        weights = np.array([[[1.0, 1.0], [1.0, 1.0]], [[0.0, 0.0], [0.0, 0.0]]])  # only the "1.0" half counts
        weighted = parcellate_means(image_4d, atlas, np.array([1]), voxel_weights=weights)

        self.assertAlmostEqual(unweighted[0, 0], 3.0)  # plain mean of 1s and 5s
        self.assertAlmostEqual(weighted[0, 0], 1.0)  # weighted mean pulled fully toward the 1.0 voxels


class ComputeMetaboliteConnectivityTests(unittest.TestCase):
    def _build_inputs(self, tmp_path: Path):
        rng = np.random.default_rng(42)
        atlas = np.zeros((6, 6, 6), dtype=int)
        atlas[:3] = 1
        atlas[3:] = 2
        atlas_path = _save_volume(tmp_path / "atlas.nii.gz", atlas)
        brainmask = np.ones((6, 6, 6))
        brainmask_path = _save_volume(tmp_path / "brainmask.nii.gz", brainmask)

        metabolite_maps = {}
        crlb_maps = {}
        for met in ("NAA", "Cr", "Glu"):
            signal = rng.uniform(5, 15, size=(6, 6, 6))
            crlb = rng.uniform(1, 10, size=(6, 6, 6))
            metabolite_maps[met] = _save_volume(tmp_path / f"{met}_signal.nii.gz", signal)
            crlb_maps[met] = _save_volume(tmp_path / f"{met}_crlb.nii.gz", crlb)

        return metabolite_maps, crlb_maps, brainmask_path, atlas_path

    def test_returns_symmetric_matrix_with_unit_diagonal(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            metabolite_maps, crlb_maps, brainmask_path, atlas_path = self._build_inputs(tmp_path)

            for method in ("pearson", "spearman", "cosine", "euclidean_distance"):
                result = compute_metabolite_connectivity(
                    metabolite_maps,
                    crlb_maps,
                    brainmask_path,
                    atlas_path,
                    [1, 2],
                    method=method,
                    n_perturbations=5,
                    nthreads=1,
                    seed=0,
                )
                sim = result.similarity
                self.assertEqual(sim.shape, (2, 2))
                np.testing.assert_allclose(sim.to_numpy(), sim.to_numpy().T, atol=1e-8)
                if method in ("pearson", "spearman"):
                    np.testing.assert_allclose(np.diag(sim.to_numpy()), 1.0, atol=1e-8)

    def test_same_seed_same_result_regardless_of_thread_count(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            metabolite_maps, crlb_maps, brainmask_path, atlas_path = self._build_inputs(tmp_path)

            single = compute_metabolite_connectivity(
                metabolite_maps, crlb_maps, brainmask_path, atlas_path, [1, 2],
                n_perturbations=8, nthreads=1, seed=7,
            )
            parallel = compute_metabolite_connectivity(
                metabolite_maps, crlb_maps, brainmask_path, atlas_path, [1, 2],
                n_perturbations=8, nthreads=4, seed=7,
            )
            np.testing.assert_allclose(single.similarity.to_numpy(), parallel.similarity.to_numpy(), atol=1e-8)

    def test_gm_fraction_path_marks_result_as_gm_weighted_and_changes_output(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            metabolite_maps, crlb_maps, brainmask_path, atlas_path = self._build_inputs(tmp_path)
            gm_fraction = np.random.default_rng(1).uniform(0, 1, size=(6, 6, 6))
            gm_path = _save_volume(tmp_path / "gm_fraction.nii.gz", gm_fraction)

            unweighted = compute_metabolite_connectivity(
                metabolite_maps, crlb_maps, brainmask_path, atlas_path, [1, 2], n_perturbations=5, seed=3,
            )
            weighted = compute_metabolite_connectivity(
                metabolite_maps, crlb_maps, brainmask_path, atlas_path, [1, 2], n_perturbations=5, seed=3,
                gm_fraction_path=gm_path,
            )

            self.assertFalse(unweighted.gm_weighted)
            self.assertTrue(weighted.gm_weighted)
            self.assertFalse(np.allclose(unweighted.parcel_concentrations, weighted.parcel_concentrations))

    def test_metadata_fields_are_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            metabolite_maps, crlb_maps, brainmask_path, atlas_path = self._build_inputs(tmp_path)
            result = compute_metabolite_connectivity(
                metabolite_maps, crlb_maps, brainmask_path, atlas_path, [1, 2],
                method="pearson", n_perturbations=7, sigma_scale=1.5, seed=0,
            )
            self.assertEqual(result.method, "pearson")
            self.assertEqual(result.n_perturbations, 7)
            self.assertEqual(result.sigma_scale, 1.5)


class ExportConnectivityTests(unittest.TestCase):
    def test_writes_expected_filename_and_npz_fields(self):
        from mrsiprep.config.settings import MRSIPrepConfig
        from mrsiprep.connectivity.export import export_connectivity

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = MRSIPrepConfig(
                tmp_path / "bids", tmp_path / "derivatives", "participant",
                participant_label=["CHUVUP013"], session_label=["V1"],
                processing_mode="parc-con",
                write_connectivity=True, connectivity_n_perturbations=4,
            )

            rng = np.random.default_rng(0)
            atlas = np.zeros((6, 6, 6), dtype=int)
            atlas[:3] = 1
            atlas[3:] = 2
            atlas_path = _save_volume(tmp_path / "atlas.nii.gz", atlas)
            brainmask_path = _save_volume(tmp_path / "brainmask.nii.gz", np.ones((6, 6, 6)))
            gm_path = _save_volume(tmp_path / "gm.nii.gz", rng.uniform(0, 1, size=(6, 6, 6)))

            metabolite_maps, crlb_maps = {}, {}
            for met in ("NAA", "Cr"):
                metabolite_maps[met] = _save_volume(tmp_path / f"{met}.nii.gz", rng.uniform(5, 15, size=(6, 6, 6)))
                crlb_maps[met] = _save_volume(tmp_path / f"{met}_crlb.nii.gz", rng.uniform(1, 10, size=(6, 6, 6)))

            regional_table = tmp_path / "regional.tsv"
            regional_table.write_text(
                "parcel_id\tparcel_name\themisphere\tmetabolite\tcoverage\tmean_gm_fraction\tmean_wm_fraction\tmean_csf_fraction\n"
                "1\tparcel-1\tL\tNAA\t1.0\t0.5\t0.3\t0.2\n"
                "2\tparcel-2\tR\tNAA\t1.0\t0.5\t0.3\t0.2\n"
            )

            outputs = export_connectivity(
                config, "CHUVUP013", "V1", regional_table, "chimeraLFMIHIFIS",
                metabolite_maps, crlb_maps, brainmask_path, atlas_path,
                gm_fraction_path=gm_path, scale=3,
            )

            matrix_npz = outputs["matrix_npz"]
            self.assertEqual(
                matrix_npz.name,
                "sub-CHUVUP013_ses-V1_atlas-chimeraLFMIHIFIS_scale3_npert-4_filt-biharmonic_pvcorr_GM_desc-connectivity_mrsi.npz",
            )
            self.assertEqual(matrix_npz.parent.name, "connectivity")
            self.assertEqual(matrix_npz.parent.parent.name, "ses-V1")
            self.assertEqual(matrix_npz.parent.parent.parent.name, "sub-CHUVUP013")

            data = np.load(matrix_npz, allow_pickle=True)
            for key in ("matrix", "parcel_concentrations", "labels_indices", "parcel_names", "metabolites", "method", "npert", "sigma_scale", "gm_weighted"):
                self.assertIn(key, data.files)
            self.assertNotIn("simmatrix_sp", data.files)
            self.assertNotIn("metabolites_leaveout", data.files)

            np.testing.assert_array_equal(data["labels_indices"], [1, 2])
            np.testing.assert_array_equal(data["parcel_names"], ["parcel-1", "parcel-2"])

    def test_already_prefixed_scale_string_does_not_double_up(self):
        from mrsiprep.connectivity.export import _connectivity_matrix_path
        from mrsiprep.config.settings import MRSIPrepConfig

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            config = MRSIPrepConfig(
                tmp_path / "bids", tmp_path / "derivatives", "participant",
                processing_mode="parc-con", write_connectivity=True,
            )
            path = _connectivity_matrix_path(config, "S1", "V1", "chimeraLFMIHIFIS", "scale3", True, 50)
            self.assertIn("_scale3_", path.name)
            self.assertNotIn("scalescale", path.name)


if __name__ == "__main__":
    unittest.main()
