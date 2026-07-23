from pathlib import Path
import unittest

from mrsiprep.cli.parser import parse_args as _parse_args

_REQUIRED_ARGS = ["--metabolites", "CrPCr", "--ref-met", "CrPCr"]


def parse_args(argv):
    return _parse_args(argv + _REQUIRED_ARGS)


class CLITests(unittest.TestCase):
    def test_cli_defaults_to_mni_norm_mode(self):
        cfg = parse_args(["/tmp/bids", "/tmp/derivatives", "participant", "--participant-label", "sub-S001"])
        self.assertEqual(cfg.processing_mode, "mni-norm")
        self.assertEqual(cfg.registration_t1_target, "brain")
        self.assertEqual(cfg.parcellation_mode, "synthseg")
        self.assertEqual(cfg.synthseg_mode, "robust")
        self.assertFalse(cfg.no_pvc)
        self.assertEqual(cfg.participant_label, ["sub-S001"])
        self.assertEqual(cfg.tissue_backend, "synthseg-fast")
        self.assertEqual(cfg.derivative_dir, Path("/tmp/derivatives/mrsiprep"))

    def test_cli_defaults_to_mni_output_space_only_and_no_t1w_resampling(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant"])
        self.assertEqual(cfg.output_spaces, ["MNI152NLin2009cAsym"])
        self.assertFalse(cfg.output_mrsi_t1w)

    def test_cli_output_mrsi_t1w_flag(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--output-mrsi-t1w"])
        self.assertTrue(cfg.output_mrsi_t1w)

    def test_cli_registration_backend_defaults_to_ants(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant"])
        self.assertEqual(cfg.registration_backend, "ants")
        self.assertEqual(cfg.ants_mrsi_to_t1_transform, "sr")
        self.assertEqual(cfg.ants_t1_to_mni_transform, "s")

    def test_cli_accepts_flirt_fnirt_registration_backend(self):
        cfg = parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--registration-backend",
            "flirt-fnirt",
            "--fsl-mrsi-to-t1-dof",
            "12",
            "--fsl-t1-to-mni-dof",
            "12",
        ])
        self.assertEqual(cfg.registration_backend, "fsl")
        self.assertEqual(cfg.fsl_cost, "corratio")

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

    def test_cli_mni_norm_accepts_brain_csf_registration_target(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--registration-t1-target", "brain-csf"])
        self.assertEqual(cfg.processing_mode, "mni-norm")
        self.assertEqual(cfg.registration_t1_target, "brain-csf")

    def test_config_rejects_unsupported_registration_target(self):
        from mrsiprep.config.settings import MRSIPrepConfig

        with self.assertRaises(ValueError):
            MRSIPrepConfig(
                "/tmp/bids", "/tmp/out", "participant",
                metabolites=["CrPCr"], ref_met="CrPCr", registration_t1_target="bogus",
            )

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

    def test_cli_fsl_deformable_defaults_on(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant"])
        self.assertTrue(cfg.fsl_deformable)
        self.assertIsNone(cfg.fsl_fnirt_warpres)
        self.assertEqual(cfg.fsl_fnirt_lambda, "300,200,150,150")

    def test_cli_no_fsl_deformable_opts_out(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant", "--registration-backend", "fsl", "--no-fsl-deformable"])
        self.assertFalse(cfg.fsl_deformable)

    def test_cli_fsl_deformable_warpres_override(self):
        cfg = parse_args([
            "/tmp/bids", "/tmp/out", "participant",
            "--registration-backend", "fsl",
            "--fsl-fnirt-warpres", "6", "6", "6",
            "--fsl-fnirt-lambda", "100,100,100",
        ])
        self.assertTrue(cfg.fsl_deformable)
        self.assertEqual(cfg.fsl_fnirt_warpres, (6, 6, 6))
        self.assertEqual(cfg.fsl_fnirt_lambda, "100,100,100")

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


class ConfigPresetTests(unittest.TestCase):
    def test_nature_comms_2025_preset_sets_parc_con_parameters(self):
        cfg = _parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--config-preset",
            "nature-comms-2025",
        ])
        self.assertEqual(cfg.processing_mode, "parc-con")
        self.assertEqual(cfg.tissue_backend, "existing")
        self.assertEqual(cfg.registration_backend, "ants")
        self.assertEqual(cfg.parcellation_mode, "chimera")
        self.assertEqual(cfg.chimera_scheme, "LFMIHIFIFS")
        self.assertTrue(cfg.write_connectivity)
        self.assertEqual(cfg.connectivity_space, "MRSI")
        self.assertEqual(cfg.metabolites, ["CrPCr", "GluGln", "GPCPCh", "NAANAAG", "Ins"])
        self.assertIsNotNone(cfg.preset_citation)
        self.assertEqual(cfg.preset_citation["doi"], "10.1038/s41467-025-66124-w")

    def test_imaging_neurosci_2026_preset_sets_mni_norm_parameters(self):
        cfg = _parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--config-preset",
            "imaging-neurosci-2026",
        ])
        self.assertEqual(cfg.processing_mode, "mni-norm")
        self.assertEqual(cfg.tissue_backend, "existing")
        self.assertEqual(cfg.ants_t1_to_mni_transform, "s")
        self.assertEqual(cfg.mni_resolution, "5mm")
        self.assertIsNotNone(cfg.preset_citation)
        self.assertEqual(cfg.preset_citation["doi"], "10.1162/imag.a.1276")

    def test_explicit_cli_flag_overrides_preset_value(self):
        cfg = _parse_args([
            "/tmp/bids",
            "/tmp/out",
            "participant",
            "--config-preset",
            "imaging-neurosci-2026",
            "--mni-resolution",
            "2mm",
        ])
        self.assertEqual(cfg.mni_resolution, "2mm")

    def test_no_preset_leaves_preset_citation_none(self):
        cfg = parse_args(["/tmp/bids", "/tmp/out", "participant"])
        self.assertIsNone(cfg.preset_citation)

    def test_unknown_preset_name_raises(self):
        with self.assertRaises(ValueError):
            _parse_args([
                "/tmp/bids",
                "/tmp/out",
                "participant",
                "--config-preset",
                "does-not-exist",
                "--metabolites",
                "CrPCr",
                "--ref-met",
                "CrPCr",
            ])
