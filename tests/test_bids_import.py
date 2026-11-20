"""Unit tests for mrsiprep.interfaces.bids_import T1w handling."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from mrsiprep.interfaces.bids_import import (
    build_mrsi_destination,
    classify_mrsi_filename,
    detect_sub_ses_from_marker,
    find_t1w_candidates,
    infer_anat_acq,
    is_t1w_candidate,
    migrate_batch,
    migrate_session_folder,
    scan_mrsi_subfolders,
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


class FindT1wCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.affine = np.eye(4)

    def _save(self, relpath: str) -> Path:
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.ones((3, 3, 3), dtype=np.float32), self.affine), path)
        return path

    def test_matches_chosen_tokens_recursively(self):
        self._save("sub1/t1_bravo_scan.nii.gz")
        self._save("sub2/nested/dir/MP2RAGE_pTx.nii.gz")
        self._save("sub3/irrelevant.nii.gz")
        found = find_t1w_candidates(self.tmp, ["bravo", "MP2RAGE_pTx"])
        names = {p.name for p in found}
        self.assertEqual(names, {"t1_bravo_scan.nii.gz", "MP2RAGE_pTx.nii.gz"})

    def test_case_insensitive(self):
        self._save("scan_BRAVO.nii.gz")
        found = find_t1w_candidates(self.tmp, ["bravo"])
        self.assertEqual(len(found), 1)

    def test_no_tokens_returns_empty(self):
        self._save("scan_bravo.nii.gz")
        self.assertEqual(find_t1w_candidates(self.tmp, []), [])


class DetectSubSesFromMarkerTests(unittest.TestCase):
    def test_detects_sub_and_ses(self):
        result = detect_sub_ses_from_marker("T105_V1_scan.nii.gz", "T", "V")
        self.assertEqual(result, {"sub": "105", "ses": "V1"})

    def test_no_match_returns_none(self):
        self.assertIsNone(detect_sub_ses_from_marker("no_markers_here.nii.gz", "T", "V"))

    def test_empty_marker_returns_none(self):
        self.assertIsNone(detect_sub_ses_from_marker("T105_V1.nii.gz", "", "V"))

    def test_case_insensitive_markers(self):
        result = detect_sub_ses_from_marker("t105_v1.nii.gz", "T", "V")
        self.assertEqual(result, {"sub": "105", "ses": "V1"})


class ClassifyMrsiFilenameTests(unittest.TestCase):
    def test_unmatched_metabolite_returns_none(self):
        self.assertIsNone(classify_mrsi_filename("Unknown_signal.nii.gz", ["NAA", "Cr"]))

    def test_defaults_to_signal_when_no_type_pattern_matches(self):
        result = classify_mrsi_filename("NAA_raw.nii.gz", ["NAA"], crlb_pattern="crlb")
        self.assertEqual(result["desc"], "signal")

    def test_crlb_pattern_detected(self):
        result = classify_mrsi_filename("NAA_crlb.nii.gz", ["NAA"], crlb_pattern="crlb")
        self.assertEqual(result["desc"], "crlb")

    def test_signal_pattern_required_when_given(self):
        # When a non-empty signal_pattern is supplied, a file matching no
        # type pattern (including signal) is not treated as signal by
        # default -- it must explicitly contain the signal token.
        self.assertIsNone(classify_mrsi_filename("NAA_raw.nii.gz", ["NAA"], signal_pattern="signal", crlb_pattern="crlb"))


class ScanMrsiSubfoldersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.affine = np.eye(4)

    def _save(self, relpath: str) -> Path:
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.ones((3, 3, 3), dtype=np.float32), self.affine), path)
        return path

    def test_scans_one_level_down_only(self):
        self._save("root/FolderA/NAA_signal.nii.gz")
        self._save("root/FolderA/nested/too_deep.nii.gz")
        result = scan_mrsi_subfolders(self.tmp / "root", ["NAA"], signal_pattern="signal")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["folder_name"], "FolderA")

    def test_unmatched_files_listed_not_dropped(self):
        self._save("root/FolderA/NAA_signal.nii.gz")
        self._save("root/FolderA/junk_file.nii.gz")
        result = scan_mrsi_subfolders(self.tmp / "root", ["NAA"], signal_pattern="signal")
        self.assertEqual(result[0]["unmatched"], ["junk_file.nii.gz"])

    def test_counts_per_type(self):
        self._save("root/FolderA/NAA_signal.nii.gz")
        self._save("root/FolderA/NAA_crlb.nii.gz")
        self._save("root/FolderA/Cr_snr.nii.gz")
        result = scan_mrsi_subfolders(
            self.tmp / "root", ["NAA", "Cr"], signal_pattern="signal", crlb_pattern="crlb", snr_pattern="snr"
        )
        self.assertEqual(result[0]["counts"], {"signal": 1, "crlb": 1, "snr": 1, "fwhm": 0})

    def test_nonexistent_root_returns_empty(self):
        self.assertEqual(scan_mrsi_subfolders(self.tmp / "missing", ["NAA"]), [])


class BuildMrsiDestinationOverrideTests(unittest.TestCase):
    def test_both_overrides_skip_filename_parsing(self):
        # Regression test: build_mrsi_destination used to call
        # parse_mrsi_filename() unconditionally even when both overrides
        # were supplied, so a filename outside ACQ_MAPPING's fixed
        # vocabulary (e.g. a custom pattern from scan_mrsi_subfolders)
        # would raise despite the caller having already resolved met/desc.
        dest = build_mrsi_destination(
            "NAA_not_a_known_token.nii.gz", "/bids", "S001", "V1", met_override="NAA", desc_override="signal"
        )
        self.assertIn("met-NAA", dest.name)
        self.assertIn("desc-signal", dest.name)

    def test_single_override_still_parses_the_rest(self):
        dest = build_mrsi_destination("NAA_crlb.nii.gz", "/bids", "S001", "V1", met_override="Custom")
        self.assertIn("met-Custom", dest.name)
        self.assertIn("desc-crlb", dest.name)


class MigrateBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bids_dir = self.tmp / "bids"
        self.affine = np.eye(4)

    def _save(self, relpath: str) -> Path:
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.ones((3, 3, 3), dtype=np.float32), self.affine), path)
        return path

    def test_migrates_anat_and_mrsi_per_pair(self):
        t1_a = self._save("t1_a.nii.gz")
        t1_b = self._save("t1_b.nii.gz")
        mrsi_a = self._save("mrsi_root/FolderA/NAA_signal.nii.gz")
        mrsi_b = self._save("mrsi_root/FolderB/Cr_signal.nii.gz")
        anat_rows = [
            {"t1_path": str(t1_a), "subject": "S001", "session": "V1", "acq": "mprage", "run": None},
            {"t1_path": str(t1_b), "subject": "S002", "session": "V1", "acq": "mprage", "run": None},
        ]
        subfolders = scan_mrsi_subfolders(self.tmp / "mrsi_root", ["NAA", "Cr"], signal_pattern="signal")
        summary = migrate_batch(self.bids_dir, anat_rows, subfolders)
        self.assertEqual(len(summary["t1"]), 2)
        self.assertEqual(len(summary["mrsi"]), 2)
        self.assertEqual(summary["errors"], [])

    def test_errors_recorded_without_aborting_other_pairs(self):
        t1_a = self._save("t1_a.nii.gz")
        anat_rows = [
            {"t1_path": "/nonexistent/path.nii.gz", "subject": "S001", "session": "V1", "acq": "mprage", "run": None},
            {"t1_path": str(t1_a), "subject": "S002", "session": "V1", "acq": "mprage", "run": None},
        ]
        summary = migrate_batch(self.bids_dir, anat_rows, [{"files": {}}, {"files": {}}])
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(len(summary["t1"]), 1)


if __name__ == "__main__":
    unittest.main()
