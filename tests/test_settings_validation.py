import unittest

from mrsiprep.config.settings import MRSIPrepConfig


def _config(**overrides):
    kwargs = dict(
        bids_dir="/tmp/bids",
        output_dir="/tmp/derivatives",
        analysis_level="participant",
        metabolites=["CrPCr"],
        ref_met="CrPCr",
    )
    kwargs.update(overrides)
    return MRSIPrepConfig(**kwargs)


class RequiredFieldTests(unittest.TestCase):
    def test_missing_metabolites_raises(self):
        with self.assertRaisesRegex(ValueError, "--metabolites"):
            _config(metabolites=[])

    def test_missing_ref_met_raises(self):
        with self.assertRaisesRegex(ValueError, "--ref-met"):
            _config(ref_met=None)


class ModeParcellationCombinationTests(unittest.TestCase):
    def test_parc_con_rejects_synthseg_parcellation(self):
        with self.assertRaisesRegex(ValueError, "parc-con requires Chimera or MNI"):
            _config(processing_mode="parc-con", parcellation_mode="synthseg")

    def test_mni_norm_rejects_non_synthseg_parcellation(self):
        with self.assertRaisesRegex(ValueError, "mni-norm only supports SynthSeg"):
            _config(processing_mode="mni-norm", parcellation_mode="chimera")

    def test_parc_con_defaults_to_chimera(self):
        cfg = _config(processing_mode="parc-con")
        self.assertEqual(cfg.parcellation_mode, "chimera")
        self.assertEqual(cfg.registration_t1_target, "brain-csf")

    def test_mni_norm_defaults_to_synthseg(self):
        cfg = _config(processing_mode="mni-norm")
        self.assertEqual(cfg.parcellation_mode, "synthseg")
        self.assertEqual(cfg.registration_t1_target, "brain")


class RegistrationBackendTests(unittest.TestCase):
    def test_flirt_fnirt_alias_normalizes_to_fsl(self):
        for alias in ("flirt/fnirt", "flirt_fnirt", "flirt-fnirt"):
            cfg = _config(registration_backend=alias)
            self.assertEqual(cfg.registration_backend, "fsl")

    def test_unsupported_registration_backend_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported registration backend"):
            _config(registration_backend="freesurfer")

    def test_fsl_backend_with_longitudinal_raises(self):
        with self.assertRaisesRegex(ValueError, "--longitudinal currently requires"):
            _config(registration_backend="fsl", longitudinal=True)

    def test_invalid_fsl_mrsi_to_t1_dof_raises(self):
        with self.assertRaisesRegex(ValueError, "--fsl-mrsi-to-t1-dof"):
            _config(fsl_mrsi_to_t1_dof=8)

    def test_invalid_fsl_t1_to_mni_dof_raises(self):
        with self.assertRaisesRegex(ValueError, "--fsl-t1-to-mni-dof"):
            _config(fsl_t1_to_mni_dof=8)

    def test_invalid_fsl_mrsi_to_t1_init_raises(self):
        with self.assertRaisesRegex(ValueError, "--fsl-mrsi-to-t1-init"):
            _config(fsl_mrsi_to_t1_init="bogus")


class EnumChoiceTests(unittest.TestCase):
    def test_unsupported_processing_mode_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported processing mode"):
            _config(processing_mode="bogus")

    def test_unsupported_synthseg_mode_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported SynthSeg mode"):
            _config(synthseg_mode="bogus")

    def test_unsupported_tissue_backend_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported tissue backend"):
            _config(tissue_backend="bogus")


class NumericClampingTests(unittest.TestCase):
    def test_nproc_and_nthreads_clamped_to_at_least_one(self):
        cfg = _config(nproc=0, nthreads=-5)
        self.assertEqual(cfg.nproc, 1)
        self.assertEqual(cfg.nthreads, 1)


if __name__ == "__main__":
    unittest.main()
