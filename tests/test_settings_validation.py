import json
import tempfile
import unittest
from pathlib import Path

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

    def test_invalid_fsl_t1_to_template_dof_raises(self):
        with self.assertRaisesRegex(ValueError, "--fsl-t1-to-template-dof"):
            _config(fsl_t1_to_template_dof=8)

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


class OutputSpaceResolutionTests(unittest.TestCase):
    """--output-spaces' space[:res-...] syntax, which replaced --mni-resolution."""

    def _t1(self, tmpdir, zoom=1.0):
        import nibabel as nib
        import numpy as np

        path = Path(tmpdir) / "t1.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), dtype="float32"), np.diag([zoom] * 3 + [1.0])), path)
        return path

    def test_bare_space_defaults_to_origres(self):
        cfg = _config(output_spaces=["MNI152NLin2009cAsym"])
        self.assertEqual(cfg.space_resolutions["MNI152NLin2009cAsym"], "origres")

    def test_res_modifier_is_parsed(self):
        cfg = _config(output_spaces=["MNI152NLin2009cAsym:res-2"])
        self.assertEqual(cfg.space_resolutions["MNI152NLin2009cAsym"], "2mm")

    def test_each_space_carries_its_own_resolution(self):
        # The reason a single global flag could not survive multi-template:
        # two spaces, two different resolutions.
        cfg = _config(output_spaces=["MNI152NLin2009cAsym:res-2", "T1w:res-1"])
        self.assertEqual(cfg.space_resolutions["MNI152NLin2009cAsym"], "2mm")
        self.assertEqual(cfg.space_resolutions["T1w"], "1mm")

    def test_aliases_still_work_with_modifiers(self):
        cfg = _config(output_spaces=["mni:res-t1wres"])
        self.assertEqual(cfg.output_spaces, ["MNI152NLin2009cAsym"])
        self.assertEqual(cfg.space_resolutions["MNI152NLin2009cAsym"], "t1wres")

    def test_unknown_modifier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported modifier"):
            _config(output_spaces=["mni:bogus-2"])

    def test_non_numeric_resolution_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported resolution"):
            _config(output_spaces=["mni:res-abc"])

    def test_unknown_space_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported output space"):
            _config(output_spaces=["notaspace"])

    def test_resolution_for_resolves_explicit_millimetres(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(output_spaces=["mni:res-5"])
            self.assertEqual(cfg.resolution_for("MNI152NLin2009cAsym", self._t1(tmpdir)), 5)

    def test_resolution_for_prefers_t1w_over_origres_when_asked(self):
        # Used where the MRSI grid is the wrong reference (subject templates,
        # the registration target); origres has no single answer there.
        with tempfile.TemporaryDirectory() as tmpdir:
            t1 = self._t1(tmpdir, zoom=2.0)
            cfg = _config(output_spaces=["mni"])  # origres
            self.assertEqual(cfg.resolution_for("MNI152NLin2009cAsym", t1, prefer_t1w=True), 2)

    def test_prefer_t1w_leaves_an_explicit_choice_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(output_spaces=["mni:res-5"])
            self.assertEqual(cfg.resolution_for("MNI152NLin2009cAsym", self._t1(tmpdir), prefer_t1w=True), 5)

    def test_unrequested_space_falls_back_to_the_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(output_spaces=["mni:res-5"])
            t1 = self._t1(tmpdir, zoom=3.0)
            self.assertEqual(cfg.resolution_for("T1w", t1, prefer_t1w=True), 3)


class NucleusResolutionTests(unittest.TestCase):
    def _bids_with_nucleus(self, tmpdir, nucleus):
        root = Path(tmpdir)
        (root / "mrsinmrs.json").write_text(json.dumps({"CommonMetadata": {"Nucleus": nucleus}}), encoding="utf-8")
        return root

    def test_defaults_to_proton(self):
        self.assertEqual(_config().nucleus, "1H")

    def test_proton_thresholds_are_unchanged_by_default(self):
        # The headline regression guard for moving these out of defaults.py.
        cfg = _config()
        self.assertEqual((cfg.snr_min, cfg.linewidth_max, cfg.crlb_max), (4.0, 0.1, 20.0))

    def test_explicit_nucleus_is_canonicalized(self):
        cfg = _config(nucleus="phosphorus", snr_min=2.0, linewidth_max=0.3, crlb_max=50.0)
        self.assertEqual(cfg.nucleus, "31P")

    def test_nucleus_is_read_from_mrsinmrs_common_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(
                bids_dir=self._bids_with_nucleus(tmpdir, "31P"),
                snr_min=2.0, linewidth_max=0.3, crlb_max=50.0,
            )
            self.assertEqual(cfg.nucleus, "31P")

    def test_explicit_nucleus_overrides_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(bids_dir=self._bids_with_nucleus(tmpdir, "31P"), nucleus="1H")
            self.assertEqual(cfg.nucleus, "1H")
            self.assertEqual(cfg.snr_min, 4.0)

    def test_explicit_threshold_wins_over_the_nucleus_default(self):
        cfg = _config(snr_min=9.5)
        self.assertEqual(cfg.snr_min, 9.5)
        # ...and the ones left unset still come from the nucleus table.
        self.assertEqual((cfg.linewidth_max, cfg.crlb_max), (0.1, 20.0))

    def test_uncurated_nucleus_without_explicit_thresholds_raises(self):
        with self.assertRaisesRegex(ValueError, "No curated voxel-quality thresholds for 31P"):
            _config(nucleus="31P")

    def test_uncurated_nucleus_is_fine_once_thresholds_are_given(self):
        cfg = _config(nucleus="2H", snr_min=1.5, linewidth_max=0.4, crlb_max=60.0)
        self.assertEqual(cfg.nucleus, "2H")
        self.assertEqual(cfg.snr_min, 1.5)

    def test_unknown_nucleus_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown nucleus"):
            _config(nucleus="19F")

    def test_metabolite_aliases_follow_the_nucleus(self):
        proton = _config().nucleus_metabolite_aliases()
        phosphorus = _config(nucleus="31P", snr_min=2.0, linewidth_max=0.3, crlb_max=50.0).nucleus_metabolite_aliases()
        self.assertIn("NAA", proton)
        self.assertIn("PCr", phosphorus)
        self.assertNotIn("NAA", phosphorus)

    def test_nucleus_reaches_provenance_via_to_dict(self):
        self.assertEqual(_config().to_dict()["nucleus"], "1H")


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
