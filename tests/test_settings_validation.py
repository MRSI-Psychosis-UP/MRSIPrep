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


class DerivedDefaultsTests(unittest.TestCase):
    def test_parcellation_mode_defaults_to_synthseg(self):
        self.assertEqual(_config().parcellation_mode, "synthseg")

    def test_synthseg_parcellation_defaults_registration_target_to_brain(self):
        cfg = _config(parcellation_mode="synthseg")
        self.assertEqual(cfg.registration_t1_target, "brain")

    def test_chimera_parcellation_defaults_registration_target_to_brain_csf(self):
        cfg = _config(parcellation_mode="chimera")
        self.assertEqual(cfg.registration_t1_target, "brain-csf")

    def test_atlas_parcellation_defaults_registration_target_to_brain_csf(self):
        cfg = _config(parcellation_mode="atlas")
        self.assertEqual(cfg.registration_t1_target, "brain-csf")

    def test_explicit_registration_target_is_not_overridden(self):
        cfg = _config(parcellation_mode="synthseg", registration_t1_target="raw")
        self.assertEqual(cfg.registration_t1_target, "raw")

    def test_tissue_backend_none_forces_no_pvc(self):
        self.assertTrue(_config(tissue_backend="none").no_pvc)

    def test_unsupported_registration_t1_target_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported registration target"):
            _config(registration_t1_target="bogus")


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
    def test_unsupported_parcellation_mode_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported parcellation mode"):
            _config(parcellation_mode="bogus")

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


class ParcellationListAccessorTests(unittest.TestCase):
    """Comma-separated parcellation options, matching Chimera's own syntax."""

    def test_single_values_still_yield_one_element_lists(self):
        cfg = _config(parcellation_mode="chimera", chimera_scheme="LFMIHIFIF", chimera_scale="3", chimera_grow="2")
        self.assertEqual(cfg.chimera_schemes(), ["LFMIHIFIF"])
        self.assertEqual(cfg.chimera_scales(), [3])
        self.assertEqual(cfg.chimera_grows(), [2])

    def test_comma_lists_are_split_in_order(self):
        cfg = _config(
            parcellation_mode="chimera", chimera_scheme="LFMIHIFIF,LFMIHIFIS", chimera_scale="1,3", chimera_grow="0,2"
        )
        self.assertEqual(cfg.chimera_schemes(), ["LFMIHIFIF", "LFMIHIFIS"])
        self.assertEqual(cfg.chimera_scales(), [1, 3])
        self.assertEqual(cfg.chimera_grows(), [0, 2])

    def test_whitespace_and_stray_commas_are_tolerated(self):
        # Mirrors chimera's own `[x for x in ... if x]` filtering.
        cfg = _config(parcellation_mode="chimera", chimera_scheme=" A , B ,", chimera_scale="1, 3,")
        self.assertEqual(cfg.chimera_schemes(), ["A", "B"])
        self.assertEqual(cfg.chimera_scales(), [1, 3])

    def test_int_values_from_a_preset_json_are_accepted(self):
        # Presets ship chimera_scale as a bare int; it must not need quoting.
        cfg = _config(parcellation_mode="chimera", chimera_scale=3, chimera_grow=2)
        self.assertEqual(cfg.chimera_scales(), [3])
        self.assertEqual(cfg.chimera_grows(), [2])

    def test_scale_accepts_the_scaleN_spelling(self):
        cfg = _config(parcellation_mode="chimera", chimera_scale="scale1,scale3")
        self.assertEqual(cfg.chimera_scales(), [1, 3])

    def test_raw_fields_round_trip_unchanged_for_provenance(self):
        cfg = _config(parcellation_mode="chimera", chimera_scheme="A,B", chimera_scale="1,3")
        self.assertEqual(cfg.to_dict()["chimera_scheme"], "A,B")
        self.assertEqual(cfg.to_dict()["chimera_scale"], "1,3")

    def test_atlas_list_is_split(self):
        cfg = _config(parcellation_mode="atlas", atlas="schaefer400,mist197")
        self.assertEqual(cfg.atlases(), ["schaefer400", "mist197"])

    def test_out_of_range_scale_raises(self):
        with self.assertRaisesRegex(ValueError, "--chimera-scale must be between 1 and 5"):
            _config(parcellation_mode="chimera", chimera_scale="1,9")

    def test_non_numeric_scale_raises_with_a_useful_message(self):
        with self.assertRaisesRegex(ValueError, "--chimera-scale must be integers"):
            _config(parcellation_mode="chimera", chimera_scale="1,abc")

    def test_negative_grow_raises(self):
        with self.assertRaisesRegex(ValueError, "--chimera-grow must not be negative"):
            _config(parcellation_mode="chimera", chimera_grow="2,-1")

    def test_empty_scheme_list_raises(self):
        with self.assertRaisesRegex(ValueError, "--chimera-scheme must name at least one"):
            _config(parcellation_mode="chimera", chimera_scheme=",")

    def test_empty_atlas_list_raises(self):
        with self.assertRaisesRegex(ValueError, "--atlas must name at least one"):
            _config(parcellation_mode="atlas", atlas=" ")

    def test_chimera_values_are_not_validated_when_that_mode_is_not_selected(self):
        # A synthseg run shouldn't be rejected for a chimera value it never reads.
        cfg = _config(parcellation_mode="synthseg", chimera_scale="99")
        self.assertEqual(cfg.parcellation_mode, "synthseg")

    def test_nine_character_schemes_are_accepted(self):
        # mrsiprep's own default (LFMIHIFIS) is 9 characters, so code length
        # is left to chimera rather than rejected here.
        cfg = _config(parcellation_mode="chimera", chimera_scheme="LFMIHIFIS")
        self.assertEqual(cfg.chimera_schemes(), ["LFMIHIFIS"])


if __name__ == "__main__":
    unittest.main()
