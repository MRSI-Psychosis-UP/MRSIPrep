import json
import tempfile
import unittest
from pathlib import Path

from mrsiprep.io.bids import BIDSLayout, Recording, _matches_filter, load_bids_filters


class RecordingPrefixTests(unittest.TestCase):
    def test_includes_session_when_present(self):
        self.assertEqual(Recording("01", "01").prefix, "sub-01_ses-01")

    def test_omits_session_when_absent(self):
        self.assertEqual(Recording("01", None).prefix, "sub-01")


class LoadBidsFiltersTests(unittest.TestCase):
    def test_none_path_returns_empty_dict(self):
        self.assertEqual(load_bids_filters(None), {})

    def test_valid_t1w_filter_is_returned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "filters.json"
            path.write_text(json.dumps({"t1w": {"acq": "mprage"}}))
            self.assertEqual(load_bids_filters(path), {"t1w": {"acq": "mprage"}})

    def test_unsupported_top_level_key_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "filters.json"
            path.write_text(json.dumps({"bold": {"task": "rest"}}))
            with self.assertRaisesRegex(ValueError, "unsupported key"):
                load_bids_filters(path)

    def test_non_dict_top_level_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "filters.json"
            path.write_text(json.dumps(["not", "a", "dict"]))
            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                load_bids_filters(path)

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "filters.json"
            path.write_text("{not valid json")
            with self.assertRaisesRegex(ValueError, "Could not parse"):
                load_bids_filters(path)


class MatchesFilterTests(unittest.TestCase):
    def test_matches_on_short_key(self):
        self.assertTrue(_matches_filter({"acq": "mprage"}, {"acq": "mprage"}))
        self.assertFalse(_matches_filter({"acq": "mprage"}, {"acq": "mp2rage"}))

    def test_matches_on_long_alias_key(self):
        self.assertTrue(_matches_filter({"acq": "mprage"}, {"acquisition": "mprage"}))

    def test_none_expected_requires_entity_absent(self):
        self.assertTrue(_matches_filter({}, {"run": None}))
        self.assertFalse(_matches_filter({"run": "01"}, {"run": None}))

    def test_all_keys_must_match(self):
        entities = {"acq": "mprage", "run": "02"}
        self.assertFalse(_matches_filter(entities, {"acq": "mprage", "run": "01"}))
        self.assertTrue(_matches_filter(entities, {"acq": "mprage", "run": "02"}))


class BidsLayoutFixture(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.bids_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _touch(self, relative: str) -> Path:
        path = self.bids_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path


class DiscoverRecordingsTests(BidsLayoutFixture):
    def test_uses_participants_allsessions_tsv_when_present(self):
        (self.bids_dir / "participants_allsessions.tsv").write_text("subject\tsession\n01\t01\n02\t\n")
        layout = BIDSLayout(self.bids_dir)
        recordings = layout.discover_recordings()
        self.assertEqual([(r.subject, r.session) for r in recordings], [("01", "01"), ("02", None)])

    def test_scans_directory_tree_when_no_participants_file(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_T1w.nii.gz")
        self._touch("sub-01/ses-02/anat/sub-01_ses-02_T1w.nii.gz")
        self._touch("sub-02/anat/sub-02_T1w.nii.gz")  # sessionless subject
        layout = BIDSLayout(self.bids_dir)
        recordings = {(r.subject, r.session) for r in layout.discover_recordings()}
        self.assertEqual(recordings, {("01", "01"), ("01", "02"), ("02", None)})

    def test_ignores_non_directory_entries_matching_sub_glob(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_T1w.nii.gz")
        (self.bids_dir / "sub-not-a-dir").touch()  # a stray file, not a directory
        layout = BIDSLayout(self.bids_dir)
        recordings = layout.discover_recordings()
        self.assertEqual([(r.subject, r.session) for r in recordings], [("01", "01")])


class RawT1Tests(BidsLayoutFixture):
    def test_returns_none_when_anat_dir_missing(self):
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.raw_t1("01", "01"))

    def test_excludes_desc_derivative_files(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_desc-brain_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.raw_t1("01", "01"))

    def test_reference_name_takes_priority_over_scoring(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-mprage_T1w.nii.gz")
        wanted = self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-lowres_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        result = layout.raw_t1("01", "01", reference_name="acq-lowres")
        self.assertEqual(result, wanted)

    def test_mprage_and_run01_score_higher_than_plain(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-other_T1w.nii.gz")
        best = self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-mprage_run-01_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertEqual(layout.raw_t1("01", "01"), best)

    def test_t1w_filter_excludes_non_matching_candidates(self):
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-mprage_T1w.nii.gz")
        wanted = self._touch("sub-01/ses-01/anat/sub-01_ses-01_acq-mp2rage_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir, filters={"t1w": {"acq": "mp2rage"}})
        self.assertEqual(layout.raw_t1("01", "01"), wanted)


class T1Tests(BidsLayoutFixture):
    def test_existing_path_pattern_returned_directly(self):
        with tempfile.NamedTemporaryFile(suffix=".nii.gz") as tmp:
            layout = BIDSLayout(self.bids_dir)
            self.assertEqual(layout.t1("01", "01", pattern=tmp.name), Path(tmp.name).resolve())

    def test_matches_skullstrip_derivative_first(self):
        derivative = self._touch("derivatives/skullstrip/sub-01/ses-01/sub-01_ses-01_desc-brain_T1w.nii.gz")
        self._touch("sub-01/ses-01/anat/sub-01_ses-01_desc-brain_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertEqual(layout.t1("01", "01"), derivative)

    def test_falls_back_to_raw_t1_when_pattern_matches_nothing(self):
        raw = self._touch("sub-01/ses-01/anat/sub-01_ses-01_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertEqual(layout.t1("01", "01", pattern="desc-brain_T1w"), raw)


class BrainMaskTests(BidsLayoutFixture):
    def test_returns_none_when_root_missing(self):
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.brain_mask("01", "01"))

    def test_finds_first_matching_pattern(self):
        wanted = self._touch("derivatives/skullstrip/sub-01/ses-01/sub-01_ses-01_desc-brain_mask.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertEqual(layout.brain_mask("01", "01"), wanted)


class Cat12ProbsegTests(BidsLayoutFixture):
    def test_returns_none_when_root_missing(self):
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.cat12_probseg("01", "01", 1))

    def test_finds_indexed_probseg(self):
        wanted = self._touch("derivatives/cat12/sub-01/ses-01/sub-01_ses-01_desc-p2_T1w.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        self.assertEqual(layout.cat12_probseg("01", "01", 2), wanted)
        self.assertIsNone(layout.cat12_probseg("01", "01", 3))


class MrsiMapTests(BidsLayoutFixture):
    def test_direct_filename_match(self):
        wanted = self._touch("derivatives/mrsi-orig/sub-01/ses-01/sub-01_ses-01_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        result = layout.mrsi_map("01", "01", desc="signal", met="CrPCr", space="orig")
        self.assertEqual(result, wanted)

    def test_falls_back_to_mrsiprep_output_tree_when_primary_empty(self):
        wanted = self._touch(
            "derivatives/mrsiprep/sub-01/ses-01/mrsi/orig/sub-01_ses-01_space-orig_met-CrPCr_desc-signal_mrsi.nii.gz"
        )
        layout = BIDSLayout(self.bids_dir)
        result = layout.mrsi_map("01", "01", desc="signal", met="CrPCr", space="orig")
        self.assertEqual(result, wanted)

    def test_returns_none_when_nothing_matches(self):
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.mrsi_map("01", "01", desc="signal", met="CrPCr"))

    def test_metabolite_alias_fallback(self):
        # NAA is a documented alias target for NAANAAG in METABOLITE_ALIASES.
        from mrsiprep.config.defaults import METABOLITE_ALIASES

        met, aliases = next((m, a) for m, a in METABOLITE_ALIASES.items() if a)
        alias = aliases[0]
        wanted = self._touch(f"derivatives/mrsi-orig/sub-01/ses-01/sub-01_ses-01_space-orig_met-{alias}_desc-signal_mrsi.nii.gz")
        layout = BIDSLayout(self.bids_dir)
        result = layout.mrsi_map("01", "01", desc="signal", met=met, space="orig")
        self.assertEqual(result, wanted)


class TransformTests(BidsLayoutFixture):
    def test_forward_mrsi_transform_paths(self):
        layout = BIDSLayout(self.bids_dir)
        forward = layout.transform("01", "01", "mrsi", direction="forward")
        self.assertEqual(
            [p.name for p in forward],
            ["sub-01_ses-01_desc-mrsi_to_t1w.syn.nii.gz", "sub-01_ses-01_desc-mrsi_to_t1w.affine.mat"],
        )

    def test_inverse_mrsi_transform_includes_affine_inv(self):
        layout = BIDSLayout(self.bids_dir)
        inverse = layout.transform("01", "01", "mrsi", direction="inverse")
        names = [p.name for p in inverse]
        self.assertIn("sub-01_ses-01_desc-mrsi_to_t1w.affine_inv.mat", names)
        self.assertIn("sub-01_ses-01_desc-mrsi_to_t1w.syn_inv.nii.gz", names)

    def test_template_stage_has_no_forced_affine_inv(self):
        layout = BIDSLayout(self.bids_dir)
        # has_inv_affine=False for "t1-template": affine_inv only included if it actually exists on disk.
        inverse = layout.transform("01", "01", "t1-template", direction="inverse")
        names = [p.name for p in inverse]
        self.assertNotIn("sub-01_ses-01_desc-t1w_to_template.affine_inv.mat", names)

    def test_template_stage_includes_affine_inv_when_present_on_disk(self):
        self._touch("derivatives/mrsiprep/sub-01/ses-01/transforms/anat/sub-01_ses-01_desc-t1w_to_template.affine_inv.mat")
        layout = BIDSLayout(self.bids_dir)
        inverse = layout.transform("01", "01", "t1-template", direction="inverse")
        names = [p.name for p in inverse]
        self.assertIn("sub-01_ses-01_desc-t1w_to_template.affine_inv.mat", names)

    def test_template_mni_stage_uses_ses_all(self):
        layout = BIDSLayout(self.bids_dir)
        forward = layout.transform("01", None, "template-mni", direction="forward")
        self.assertTrue(all("ses-all" in str(p) for p in forward))
        self.assertTrue(all(p.name.startswith("sub-01_ses-all_desc-template_to_mni") for p in forward))

    def test_unsupported_stage_raises(self):
        layout = BIDSLayout(self.bids_dir)
        with self.assertRaisesRegex(ValueError, "Unsupported transform stage"):
            layout.transform("01", "01", "bogus-stage")


class ChimeraAtlasTests(BidsLayoutFixture):
    def test_returns_none_when_root_missing(self):
        layout = BIDSLayout(self.bids_dir)
        self.assertIsNone(layout.chimera_atlas("01", "01", "LFMIHIFIFF", 3))

    def test_t1w_space_normalizes_to_orig_token(self):
        wanted = self._touch(
            "derivatives/chimera-atlases/sub-01/ses-01/anat/sub-01_ses-01_space-orig_atlas-chimeraLFMIHIFIFF_desc-scale3grow2mm_dseg.nii.gz"
        )
        layout = BIDSLayout(self.bids_dir)
        result = layout.chimera_atlas("01", "01", "LFMIHIFIFF", 3, grow=2, space="T1w")
        self.assertEqual(result, wanted)


if __name__ == "__main__":
    unittest.main()
