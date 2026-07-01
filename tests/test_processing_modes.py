import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np
import pandas as pd

from mrsiprep.parcellation.atlas_registry import available_bundled_atlases, load_mni_atlas
from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.parcellation.metprofiles import export_metprofile_npz
from mrsiprep.reports.parcel_qc import write_parcel_qc
from mrsiprep.utils.images import round_mm_resolution


class ProcessingModeTests(unittest.TestCase):
    def test_mni_template_resolution_is_integer(self):
        self.assertEqual(round_mm_resolution(0.8), 1)
        self.assertEqual(round_mm_resolution(1.2), 1)
        self.assertEqual(round_mm_resolution(1.6), 2)

    def test_bundled_mni_atlas_is_discoverable(self):
        self.assertIn("chimera-LFMIHIFIS-3", available_bundled_atlases())
        config = SimpleNamespace(atlas="chimera-LFMIHIFIS-3")
        image, labels, name = load_mni_atlas(config, "/tmp/unused-atlas-work")
        self.assertTrue(image.exists())
        self.assertTrue(labels.exists())
        self.assertEqual(name, "chimeraLFMIHIFIS3")

    def test_full_mode_metprofile_export_matches_legacy_core_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas_data = np.repeat(np.array([[[1], [1]], [[2], [2]]], dtype=np.int16), 2, axis=2)
            atlas = root / "atlas.nii.gz"
            nib.save(nib.Nifti1Image(atlas_data, np.eye(4)), atlas)
            labels = root / "labels.tsv"
            pd.DataFrame({"parcel_id": [1, 2], "parcel_name": ["left", "right"], "hemisphere": ["L", "R"]}).to_csv(labels, sep="\t", index=False)
            regional = root / "regional.tsv"
            pd.DataFrame(
                {
                    "parcel_id": [1, 2, 1, 2],
                    "metabolite": ["CrPCr", "CrPCr", "GluGln", "GluGln"],
                    "mean": [1.0, 2.0, 3.0, np.nan],
                    "median": [1.0, 2.0, 3.0, np.nan],
                    "weighted_mean": [1.0, 2.0, 3.0, np.nan],
                }
            ).to_csv(regional, sep="\t", index=False)
            maps = {}
            for metabolite in ("CrPCr", "GluGln"):
                path = root / f"{metabolite}.nii.gz"
                nib.save(nib.Nifti1Image(np.ones_like(atlas_data, dtype=np.float32), np.eye(4)), path)
                maps[metabolite] = path
            config = SimpleNamespace(
                regional_summary="mean",
                filter_biharmonic=True,
                no_pvc=False,
                mrsi_parcel_dir=root / "mrsi_parcel",
                bids_dir=root / "dataset",
                processing_mode="parc-con",
                chimera_grow=2,
            )
            parcels = ParcellationResult(atlas_mrsi=atlas, labels=labels, mode="chimera", atlas_name="chimeraLFMIHIFIS", scale="3")
            output = export_metprofile_npz(config, "S001", "V1", maps, None, parcels, regional, None)
            archive = np.load(output, allow_pickle=True)
            self.assertEqual(archive["metab_profiles"].shape, (2, 2))
            self.assertEqual(archive["metabolites"].tolist(), ["CrPCr", "GluGln"])
            self.assertEqual(archive["parcel_labels"].tolist(), [1, 2])
            self.assertIn("pvcorr_GM", output.name)

    def test_parcel_qc_reports_t1_coverage_and_mean_crlb(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas_data = np.repeat(np.array([[[1], [1]], [[2], [2]]], dtype=np.int16), 2, axis=2)
            atlas_t1 = root / "atlas_t1.nii.gz"
            atlas_mrsi = root / "atlas_mrsi.nii.gz"
            reference = root / "t1.nii.gz"
            brainmask = root / "brainmask.nii.gz"
            crlb = root / "crlb.nii.gz"
            qcmask = root / "qcmask.nii.gz"
            for path, data in (
                (atlas_t1, atlas_data),
                (atlas_mrsi, atlas_data),
                (reference, np.ones_like(atlas_data)),
                (brainmask, np.repeat(np.array([[[1], [0]], [[1], [0]]], dtype=np.uint8), 2, axis=2)),
                (crlb, np.repeat(np.array([[[5], [15]], [[10], [20]]], dtype=np.float32), 2, axis=2)),
                (qcmask, np.ones_like(atlas_data, dtype=np.uint8)),
            ):
                nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            labels = root / "labels.tsv"
            pd.DataFrame({"parcel_id": [1, 2], "parcel_name": ["left", "right"]}).to_csv(labels, sep="\t", index=False)
            config = SimpleNamespace(
                derivative_dir=root / "derivatives",
                overwrite_transform=True,
                overwrite=True,
                nthreads=2,
            )
            parcels = ParcellationResult(atlas_t1=atlas_t1, atlas_mrsi=atlas_mrsi, labels=labels, mode="synthseg", atlas_name="synthseg")

            def copy_transform(_fixed, moving, _transforms, output, **_kwargs):
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(moving, output)
                return Path(output)

            with patch("mrsiprep.reports.parcel_qc.apply_transforms", side_effect=copy_transform):
                output = write_parcel_qc(
                    config,
                    "S001",
                    "V1",
                    parcels,
                    reference,
                    brainmask,
                    [root / "transform.mat"],
                    {"CrPCr": crlb},
                    {"CrPCr": qcmask},
                )
            table = pd.read_csv(output, sep="\t").set_index("parcel_id")
            self.assertEqual(table.loc[1, "anatomical_coverage_percent"], 50.0)
            self.assertEqual(table.loc[2, "anatomical_coverage_percent"], 50.0)
            self.assertEqual(table.loc[1, "mean_crlb"], 10.0)
            self.assertEqual(table.loc[2, "mean_crlb"], 15.0)


if __name__ == "__main__":
    unittest.main()
