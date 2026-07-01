from pathlib import Path
import unittest

from mrsiprep.cli.parser import parse_args


class CLITests(unittest.TestCase):
    def test_cli_defaults_to_mni_norm_mode(self):
        cfg = parse_args(["/tmp/bids", "/tmp/derivatives", "participant", "--participant-label", "sub-S001"])
        self.assertEqual(cfg.processing_mode, "mni-norm")
        self.assertEqual(cfg.registration_t1_target, "brain")
        self.assertEqual(cfg.parcellation_mode, "synthseg")
        self.assertEqual(cfg.synthseg_mode, "robust")
        self.assertTrue(cfg.no_pvc)
        self.assertEqual(cfg.participant_label, ["sub-S001"])
        self.assertEqual(cfg.tissue_backend, "synthseg-fast")
        self.assertEqual(cfg.derivative_dir, Path("/tmp/derivatives/mrsiprep"))

    def test_cli_parc_con_mode_defaults_to_chimera_and_synthseg_brain(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--mode", "parc-con"])
        self.assertEqual(cfg.processing_mode, "parc-con")
        self.assertEqual(cfg.registration_t1_target, "brain-csf")
        self.assertEqual(cfg.parcellation_mode, "chimera")
        self.assertEqual(cfg.derivative_dir, Path("/tmp/out/mrsiprep"))
        self.assertFalse(cfg.no_pvc)

    def test_cli_does_not_duplicate_explicit_mrsiprep_output_directory(self):
        cfg = parse_args(["/tmp/bids", "/tmp/derivatives/mrsiprep", "participant"])
        self.assertEqual(cfg.derivative_dir, Path("/tmp/derivatives/mrsiprep"))

    def test_cli_parc_con_mode_accepts_mni_atlas(self):
        cfg = parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--mode",
            "parc-con",
            "--parcellation-mode",
            "mni",
            "--atlas",
            "chimera-LFMIHIFIS-3",
            "--synthseg-mode",
            "robust",
        ])
        self.assertEqual(cfg.parcellation_mode, "mni")
        self.assertEqual(cfg.synthseg_mode, "robust")

    def test_cli_normalizes_mni_output_space_alias(self):
        cfg = parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--mode",
            "parc-con",
            "--parcellation-mode",
            "mni",
            "--output-spaces",
            "mni",
        ])
        self.assertEqual(cfg.output_spaces, ["MNI152NLin2009cAsym"])

    def test_cli_rejects_chimera_in_mni_norm_mode(self):
        with self.assertRaises(ValueError):
            parse_args(["/tmp/bids", "/tmp/out", "participant", "--parcellation-mode", "chimera"])

    def test_cli_synthseg_fast_option(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--tissue-backend", "synthseg-fast"])
        self.assertEqual(cfg.tissue_backend, "synthseg-fast")

    def test_cli_none_tissue_backend_forces_no_pvc(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--mode", "parc-con", "--tissue-backend", "none"])
        self.assertEqual(cfg.tissue_backend, "none")
        self.assertTrue(cfg.no_pvc)

    def test_cli_validate_only_option(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--validate-only"])
        self.assertTrue(cfg.validate_only)

    def test_cli_fs_subjects_dir_option(self):
        cfg = parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--mode",
            "parc-con",
            "--parcellation-mode",
            "chimera",
            "--fs-subjects-dir",
            "/tmp/fs",
        ])
        self.assertEqual(cfg.freesurfer_dir, Path("/tmp/fs"))
