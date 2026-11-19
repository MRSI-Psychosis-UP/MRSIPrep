"""Unit tests for mrsiprep.interfaces.bids_import T1w handling."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.interfaces.bids_import import (
    infer_anat_acq,
    is_t1w_candidate,
    migrate_session_folder,
)


class InferAnatAcqTests(unittest.TestCase):
    def test_mprage(self):
        self.assertEqual(infer_anat_acq("sub-01_mprage.nii.gz"), "mprage")

    def test_memprage_before_mprage(self):
        # "memprage" also contains "mprage" as a substring; the more
        # specific token must win.
        self.assertEqual(infer_anat_acq("sub-01_memprage.nii.gz"), "memprage")

    def test_mp2rage(self):
        self.assertEqual(infer_anat_acq("sub-01_mp2rage.nii.gz"), "mp2rage")

    def test_ptx(self):
        self.assertEqual(infer_anat_acq("sub-01_t1_ptx.nii.gz"), "ptx")

    def test_t1w_token(self):
        self.assertEqual(infer_anat_acq("sub-01_ses-V1_T1w.nii.gz"), "t1w")

    def test_bare_t1_token(self):
        self.assertEqual(infer_anat_acq("sub-01_T1_raw.nii.gz"), "t1")

    def test_unknown(self):
        self.assertEqual(infer_anat_acq("sub-01_anatomical.nii.gz"), "unknown")


class IsT1wCandidateTests(unittest.TestCase):
    def test_matches_t1(self):
        self.assertTrue(is_t1w_candidate("sub-01_T1.nii.gz"))

    def test_matches_mprage(self):
        self.assertTrue(is_t1w_candidate("sub-01_mprage.nii.gz"))

    def test_matches_ptx(self):
        self.assertTrue(is_t1w_candidate("sub-01_ptx.nii.gz"))

    def test_rejects_unrelated_file(self):
        self.assertFalse(is_t1w_candidate("sub-01_flair.nii.gz"))


class MigrateSessionFolderMultipleT1wTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = self.tmp / "Results_S001_V1"
        self.source.mkdir(parents=True)
        self.bids_dir = self.tmp / "bids"
        self.affine = np.eye(4)

    def _save(self, name: str) -> Path:
        path = self.source / name
        nib.save(nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), self.affine), path)
        return path

    def test_single_t1w_file_keeps_unsuffixed_name(self):
        self._save("mprage_scan.nii.gz")
        summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        self.assertEqual(len(summary["t1"]), 1)
        out = Path(summary["t1"][0])
        self.assertEqual(out.name, "sub-S001_ses-V1_acq-mprage_T1w.nii.gz")
        self.assertNotIn("run-", out.name)

    def test_multiple_same_acq_t1w_files_get_run_suffixes(self):
        self._save("mprage_a.nii.gz")
        self._save("mprage_b.nii.gz")
        summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        self.assertEqual(len(summary["t1"]), 2)
        names = sorted(Path(p).name for p in summary["t1"])
        self.assertEqual(
            names,
            [
                "sub-S001_ses-V1_acq-mprage_run-01_T1w.nii.gz",
                "sub-S001_ses-V1_acq-mprage_run-02_T1w.nii.gz",
            ],
        )

    def test_different_acq_types_imported_without_clobbering(self):
        self._save("mprage_scan.nii.gz")
        self._save("memprage_scan.nii.gz")
        self._save("t1_ptx_scan.nii.gz")
        summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        self.assertEqual(len(summary["t1"]), 3)
        names = {Path(p).name for p in summary["t1"]}
        self.assertEqual(
            names,
            {
                "sub-S001_ses-V1_acq-mprage_T1w.nii.gz",
                "sub-S001_ses-V1_acq-memprage_T1w.nii.gz",
                "sub-S001_ses-V1_acq-ptx_T1w.nii.gz",
            },
        )

    def test_run_assignment_is_deterministic_by_filename(self):
        # source.rglob() is consumed in sorted order, so run numbering is
        # stable regardless of which file was created/saved first.
        self._save("mprage_zzz.nii.gz")
        self._save("mprage_aaa.nii.gz")
        first_summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        shutil.rmtree(self.bids_dir)
        second_summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        self.assertEqual(sorted(first_summary["t1"]), sorted(second_summary["t1"]))

    def test_rerun_without_overwrite_skips_existing_runs(self):
        self._save("mprage_a.nii.gz")
        self._save("mprage_b.nii.gz")
        migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        summary = migrate_session_folder(self.source, self.bids_dir, subject="S001", session="V1")
        self.assertEqual(len(summary["t1"]), 0)
        self.assertEqual(len(summary["skipped"]), 2)


if __name__ == "__main__":
    unittest.main()
