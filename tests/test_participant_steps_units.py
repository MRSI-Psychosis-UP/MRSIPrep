"""Tests for the per-stage `_step_*` orchestration functions in
workflows/participant.py, plus `_build_subject_templates`. These wrap calls
into the various workflow modules (already unit-tested on their own) behind
a `with debug.step(...)` context manager -- the thing worth verifying here
is the data threading and processing_mode/no_pvc gating logic itself, so
every collaborator is mocked.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.cli.parser import parse_args as _parse_args
from mrsiprep.io.bids import Recording
from mrsiprep.workflows import participant as P

_REQUIRED_ARGS = ["--metabolites", "CrPCr", "--ref-met", "CrPCr"]


def make_config(argv, **overrides):
    cfg = _parse_args(argv + _REQUIRED_ARGS)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _debug():
    return MagicMock()


class BuildSubjectTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config(["/tmp/bids", "/tmp/out", "participant"], longitudinal=True)
        self.debug = _debug()

    def test_single_session_subject_is_skipped(self):
        with patch("mrsiprep.io.bids.BIDSLayout"), patch(
            "mrsiprep.registration.subject_template.build_subject_template"
        ) as build_fn:
            templates = P._build_subject_templates(self.config, [Recording("01", "01")], self.debug)
        self.assertEqual(templates, {})
        build_fn.assert_not_called()

    def test_session_less_recording_is_ignored(self):
        with patch("mrsiprep.io.bids.BIDSLayout"), patch(
            "mrsiprep.registration.subject_template.build_subject_template"
        ) as build_fn:
            templates = P._build_subject_templates(self.config, [Recording("01", None)], self.debug)
        self.assertEqual(templates, {})
        build_fn.assert_not_called()

    def test_multi_session_subject_builds_one_template(self):
        ready = [Recording("01", "01"), Recording("01", "02")]
        anat_01 = SimpleNamespace(registration_t1w=Path("/deriv/ses-01_T1w.nii.gz"))
        anat_02 = SimpleNamespace(registration_t1w=Path("/deriv/ses-02_T1w.nii.gz"))
        with patch("mrsiprep.io.bids.BIDSLayout"), patch(
            "mrsiprep.workflows.participant.validate_recording", return_value=(Path("t1"), object())
        ), patch(
            "mrsiprep.workflows.participant._step_tissue_segmentation", return_value=(Path("t1"), None, None, None)
        ), patch(
            "mrsiprep.workflows.participant._step_anatomical_prep", side_effect=[anat_01, anat_02]
        ), patch(
            "mrsiprep.registration.subject_template.build_subject_template", return_value="template-01"
        ) as build_fn:
            templates = P._build_subject_templates(self.config, ready, self.debug)

        self.assertEqual(templates, {"01": "template-01"})
        build_fn.assert_called_once_with(self.config, "01", {"01": anat_01.registration_t1w, "02": anat_02.registration_t1w})


class StepTissueSegmentationTests(unittest.TestCase):
    def _cfg(self, mode, **overrides):
        return make_config(["/tmp/bids", "/tmp/out", "participant", "--mode", mode], **overrides)

    def test_mni_norm_raises_without_raw_t1(self):
        config = self._cfg("mni-norm")
        with self.assertRaisesRegex(FileNotFoundError, "SynthSeg\\+FAST segmentation"):
            P._step_tissue_segmentation(config, "01", "01", None, Path("t1"), _debug())

    def test_mni_norm_keeps_t1_path_when_target_is_raw(self):
        config = self._cfg("mni-norm", registration_t1_target="raw")
        with patch("mrsiprep.workflows.participant.segment_t1_synthseg_fast", return_value={"GM": "gm"}) as seg, patch(
            "mrsiprep.workflows.participant.synthseg_fast_csf_probseg_path", return_value=Path("p3")
        ):
            t1_path, tissue, p3, mask = P._step_tissue_segmentation(config, "01", "01", Path("raw"), Path("orig_t1"), _debug())
        seg.assert_called_once_with(config, "01", "01", Path("raw"))
        self.assertEqual(t1_path, Path("orig_t1"))  # unchanged: target is "raw", not "brain"
        self.assertEqual(tissue, {"GM": "gm"})
        self.assertEqual(p3, Path("p3"))
        self.assertIsNone(mask)

    def test_mni_norm_overrides_t1_path_when_target_is_brain(self):
        config = self._cfg("mni-norm", registration_t1_target="brain")
        with patch("mrsiprep.workflows.participant.segment_t1_synthseg_fast"), patch(
            "mrsiprep.workflows.participant.synthseg_fast_csf_probseg_path", return_value=Path("p3")
        ), patch(
            "mrsiprep.workflows.participant.synthseg_fast_brain_path", return_value=Path("brain")
        ), patch(
            "mrsiprep.workflows.participant.synthseg_fast_brain_mask_path", return_value=Path("brain_mask")
        ):
            t1_path, _tissue, _p3, mask = P._step_tissue_segmentation(config, "01", "01", Path("raw"), Path("orig_t1"), _debug())
        self.assertEqual(t1_path, Path("brain"))
        self.assertEqual(mask, Path("brain_mask"))

    def test_parc_con_synthseg_fast_raises_without_raw_t1(self):
        config = self._cfg("parc-con", tissue_backend="synthseg-fast")
        with self.assertRaisesRegex(FileNotFoundError, "SynthSeg\\+FAST segmentation"):
            P._step_tissue_segmentation(config, "01", "01", None, Path("t1"), _debug())

    def test_parc_con_synthseg_fast_always_overrides_brain_and_mask(self):
        config = self._cfg("parc-con", tissue_backend="synthseg-fast", registration_t1_target="raw")
        with patch("mrsiprep.workflows.participant.segment_t1_synthseg_fast"), patch(
            "mrsiprep.workflows.participant.synthseg_fast_brain_path", return_value=Path("brain")
        ), patch(
            "mrsiprep.workflows.participant.synthseg_fast_brain_mask_path", return_value=Path("brain_mask")
        ), patch(
            "mrsiprep.workflows.participant.synthseg_fast_csf_probseg_path", return_value=Path("p3")
        ):
            t1_path, _tissue, p3, mask = P._step_tissue_segmentation(config, "01", "01", Path("raw"), Path("orig_t1"), _debug())
        # Unlike mni-norm, parc-con+synthseg-fast overrides regardless of registration_t1_target.
        self.assertEqual(t1_path, Path("brain"))
        self.assertEqual(mask, Path("brain_mask"))
        self.assertEqual(p3, Path("p3"))

    def test_parc_con_existing_backend_is_a_no_op(self):
        config = self._cfg("parc-con", tissue_backend="existing")
        t1_path, tissue, p3, mask = P._step_tissue_segmentation(config, "01", "01", Path("raw"), Path("orig_t1"), _debug())
        self.assertEqual(t1_path, Path("orig_t1"))
        self.assertIsNone(tissue)
        self.assertIsNone(p3)
        self.assertIsNone(mask)


class StepAnatomicalPrepTests(unittest.TestCase):
    def test_delegates_to_prepare_anatomical(self):
        config = SimpleNamespace()
        with patch("mrsiprep.workflows.participant.prepare_anatomical", return_value="anat-result") as prep:
            result = P._step_anatomical_prep(config, "01", "01", Path("t1"), Path("p3"), Path("mask"), _debug())
        prep.assert_called_once_with(config, "01", "01", Path("t1"), p3_override=Path("p3"), brain_mask_override=Path("mask"))
        self.assertEqual(result, "anat-result")


class StepMrsiPreprocessingTests(unittest.TestCase):
    def _mrsi(self, t1_correction_provenance=None):
        return SimpleNamespace(
            raw_maps={"raw": 1}, preproc_maps={"preproc": 1}, corrected_maps=None, t1_correction_provenance=t1_correction_provenance
        )

    def test_without_t1_correction_skips_that_qc_section(self):
        with patch("mrsiprep.workflows.participant.run_mrsi_workflow", return_value=self._mrsi()), patch(
            "mrsiprep.workflows.participant.build_mrsi_raw_qc_sections", return_value=["raw"]
        ), patch(
            "mrsiprep.workflows.participant.build_ventricle_qc_sections", return_value=["ventricle"]
        ), patch(
            "mrsiprep.workflows.participant.build_mrsi_preproc_qc_sections", return_value=["preproc"]
        ), patch(
            "mrsiprep.workflows.participant.build_t1_correction_qc_sections"
        ) as t1_corr:
            mrsi, qc_raw, qc_preproc, qc_t1corr = P._step_mrsi_preprocessing(SimpleNamespace(), "01", "01", object(), _debug())
        t1_corr.assert_not_called()
        self.assertIsNone(qc_t1corr)
        self.assertEqual(qc_raw, ["raw", "ventricle"])
        self.assertEqual(qc_preproc, ["preproc"])

    def test_with_t1_correction_builds_that_qc_section(self):
        mrsi_obj = self._mrsi(t1_correction_provenance="prov")
        with patch("mrsiprep.workflows.participant.run_mrsi_workflow", return_value=mrsi_obj), patch(
            "mrsiprep.workflows.participant.build_mrsi_raw_qc_sections", return_value=[]
        ), patch(
            "mrsiprep.workflows.participant.build_ventricle_qc_sections", return_value=[]
        ), patch(
            "mrsiprep.workflows.participant.build_mrsi_preproc_qc_sections", return_value=[]
        ), patch(
            "mrsiprep.workflows.participant.build_t1_correction_qc_sections", return_value=["t1corr"]
        ) as t1_corr:
            _mrsi, _qc_raw, _qc_preproc, qc_t1corr = P._step_mrsi_preprocessing(SimpleNamespace(), "01", "01", object(), _debug())
        t1_corr.assert_called_once()
        self.assertEqual(qc_t1corr, ["t1corr"])


class StepRegistrationTests(unittest.TestCase):
    def test_threads_mrsi_and_anat_fields_through(self):
        mrsi = SimpleNamespace(reference=Path("ref"), brainmask=Path("mask"))
        anat = SimpleNamespace(registration_t1w=Path("t1"), registration_mask=Path("anat_mask"))
        with patch("mrsiprep.workflows.participant.run_registration_workflow", return_value="reg-result") as reg:
            result = P._step_registration(SimpleNamespace(), "01", "01", mrsi, anat, _debug())
        reg.assert_called_once_with(
            unittest.mock.ANY, "01", "01", Path("ref"), Path("t1"), Path("anat_mask"), mrsi_mask=Path("mask"), subject_template=None
        )
        self.assertEqual(result, "reg-result")

    def test_passes_through_explicit_subject_template(self):
        mrsi = SimpleNamespace(reference=Path("ref"), brainmask=Path("mask"))
        anat = SimpleNamespace(registration_t1w=Path("t1"), registration_mask=Path("anat_mask"))
        with patch("mrsiprep.workflows.participant.run_registration_workflow") as reg:
            P._step_registration(SimpleNamespace(), "01", "01", mrsi, anat, _debug(), subject_template="tmpl")
        self.assertEqual(reg.call_args.kwargs["subject_template"], "tmpl")


class StepTissueProbmapsTests(unittest.TestCase):
    def test_runs_unconditionally_regardless_of_mode(self):
        # No gating left in the function at all (its mode guard was already
        # dead code, since it covered every valid processing_mode) -- confirm
        # it runs the same way for both real modes.
        for mode in ("parc-con", "mni-norm"):
            config = SimpleNamespace(processing_mode=mode)
            anat = SimpleNamespace(registration_t1w=Path("t1"), registration_mask=Path("mask"))
            mrsi = SimpleNamespace(reference=Path("ref"))
            registration = SimpleNamespace(mrsi_to_t1=SimpleNamespace(inverse="inv"))
            with patch("mrsiprep.workflows.participant.run_tissue_workflow", return_value="tissue-result") as run_fn:
                result = P._step_tissue_probmaps(config, "01", "01", anat, mrsi, registration, "precomputed", _debug())
            self.assertEqual(result, "tissue-result", msg=mode)
            run_fn.assert_called_once_with(
                config, "01", "01", Path("t1"), Path("mask"), Path("ref"), "inv", precomputed_tissue_t1="precomputed"
            )


class StepPvcTests(unittest.TestCase):
    def _mrsi(self):
        return SimpleNamespace(preproc_maps={"preproc": 1}, reference=Path("ref"), brainmask=Path("mask"), corrected_maps=None)

    def test_no_pvc_flag_skips_correction(self):
        config = SimpleNamespace(processing_mode="parc-con", no_pvc=True)
        mrsi = self._mrsi()
        with patch("mrsiprep.workflows.participant.create_tissue_4d") as tissue_4d, patch(
            "mrsiprep.workflows.participant.run_pvc"
        ) as pvc:
            corrected, tissue4d = P._step_pvc(config, "01", "01", mrsi, SimpleNamespace(mrsi={}), _debug())
        tissue_4d.assert_not_called()
        pvc.assert_not_called()
        self.assertEqual(corrected, mrsi.preproc_maps)
        self.assertIsNone(tissue4d)

    def test_missing_tissue_raises(self):
        config = SimpleNamespace(processing_mode="parc-con", no_pvc=False)
        with self.assertRaisesRegex(ValueError, "PVC requires tissue segmentation"):
            P._step_pvc(config, "01", "01", self._mrsi(), None, _debug())

    def test_parc_con_runs_pvc_and_mutates_mrsi_corrected_maps(self):
        config = SimpleNamespace(processing_mode="parc-con", no_pvc=False)
        mrsi = self._mrsi()
        tissue = SimpleNamespace(mrsi={"GM": Path("gm")})
        with patch("mrsiprep.workflows.participant.create_tissue_4d", return_value="tissue_4d") as tissue_4d, patch(
            "mrsiprep.workflows.participant.run_pvc", return_value={"corrected": 1}
        ) as pvc:
            corrected, tissue4d = P._step_pvc(config, "01", "01", mrsi, tissue, _debug())
        tissue_4d.assert_called_once_with(config, "01", "01", {"GM": Path("gm")}, Path("ref"))
        pvc.assert_called_once_with(config, "01", "01", {"preproc": 1}, "tissue_4d", Path("mask"), Path("ref"))
        self.assertEqual(corrected, {"corrected": 1})
        self.assertEqual(tissue4d, "tissue_4d")
        self.assertEqual(mrsi.corrected_maps, {"corrected": 1})  # mutated as a side effect

    def test_mni_norm_is_also_pvc_eligible(self):
        config = SimpleNamespace(processing_mode="mni-norm", no_pvc=False)
        mrsi = self._mrsi()
        tissue = SimpleNamespace(mrsi={})
        with patch("mrsiprep.workflows.participant.create_tissue_4d", return_value="t4d"), patch(
            "mrsiprep.workflows.participant.run_pvc", return_value="corrected"
        ) as pvc:
            corrected, _tissue4d = P._step_pvc(config, "01", "01", mrsi, tissue, _debug())
        pvc.assert_called_once()
        self.assertEqual(corrected, "corrected")


class StepResamplingTests(unittest.TestCase):
    def _args(self, t1_to_mni):
        anat = SimpleNamespace(registration_t1w=Path("t1"))
        mrsi = SimpleNamespace(reference=Path("ref"), crlb_maps={}, snr_map=None, linewidth_map=None)
        registration = SimpleNamespace(mrsi_to_t1=SimpleNamespace(forward="fwd"), t1_to_mni=t1_to_mni)
        return anat, mrsi, registration

    def test_with_mni_registration_resolves_resolution_and_uses_its_forward_transform(self):
        anat, mrsi, registration = self._args(SimpleNamespace(forward="mni_fwd"))
        config = make_config(["/tmp/bids", "/tmp/out", "participant"], mni_resolution="native")
        transformed = {"T1w": {"CrPCr": Path("t1w_map")}, "MNI152NLin2009cAsym": {"CrPCr": Path("mni_map")}}
        with patch("mrsiprep.workflows.participant.transform_mrsi_maps", return_value=transformed) as tmm, patch(
            "mrsiprep.workflows.participant.resolve_mni_resolution", return_value=2.0
        ) as resolve_res, patch(
            "mrsiprep.workflows.participant.build_t1w_alignment_sections", return_value=["t1w-qc"]
        ) as t1w_qc, patch(
            "mrsiprep.workflows.participant.build_mni_alignment_sections", return_value=["mni-qc"]
        ) as mni_qc:
            result = P._step_resampling(config, "01", "01", anat, mrsi, registration, {"CrPCr": Path("orig")}, Path("raw_t1"), _debug())
        resolve_res.assert_called_once_with("native", Path("t1"), Path("ref"))
        self.assertEqual(tmm.call_args.args[5], "mni_fwd")
        t1w_qc.assert_called_once_with(
            config, "01", "01", Path("raw_t1"), Path("t1w_map"), orig_ref_map_path=Path("orig"), mrsi_to_t1_transforms="fwd"
        )
        mni_qc.assert_called_once_with(config, "01", "01", Path("mni_map"), mni_resolution=2.0)
        self.assertEqual(result, (transformed, ["t1w-qc"], ["mni-qc"]))

    def test_without_mni_registration_skips_resolution_lookup(self):
        anat, mrsi, registration = self._args(None)
        config = make_config(["/tmp/bids", "/tmp/out", "participant"], mni_resolution="native")
        transformed = {"T1w": {}, "MNI152NLin2009cAsym": {}}
        with patch("mrsiprep.workflows.participant.transform_mrsi_maps", return_value=transformed) as tmm, patch(
            "mrsiprep.workflows.participant.resolve_mni_resolution"
        ) as resolve_res, patch("mrsiprep.workflows.participant.build_t1w_alignment_sections"), patch(
            "mrsiprep.workflows.participant.build_mni_alignment_sections"
        ) as mni_qc:
            P._step_resampling(config, "01", "01", anat, mrsi, registration, {}, Path("raw_t1"), _debug())
        resolve_res.assert_not_called()
        self.assertIsNone(tmm.call_args.args[5])  # no t1_to_mni forward transform
        self.assertIsNone(mni_qc.call_args.kwargs["mni_resolution"])


class StepLeakageQcTests(unittest.TestCase):
    def test_delegates_to_write_signal_leakage_qc(self):
        anat = SimpleNamespace(registration_mask=Path("mask"))
        with patch("mrsiprep.workflows.participant.write_signal_leakage_qc", return_value="leakage-qc") as fn:
            result = P._step_leakage_qc(SimpleNamespace(), "01", "01", anat, {"T1w": {}}, _debug())
        fn.assert_called_once_with(unittest.mock.ANY, "01", "01", {"T1w": {}}, Path("mask"))
        self.assertEqual(result, "leakage-qc")


class StepSynthsegParcellationQcTests(unittest.TestCase):
    def _mrsi(self):
        return SimpleNamespace(reference=Path("ref"), brainmask=Path("mask"), crlb_maps={}, qcmasks={})

    def test_with_t1_to_mni_forward_passed_to_figures(self):
        registration = SimpleNamespace(mrsi_to_t1=SimpleNamespace(inverse="inv"), t1_to_mni=SimpleNamespace(forward="mni_fwd"))
        parcels = SimpleNamespace(atlas_t1="atlas_t1", atlas_mrsi="atlas_mrsi")
        with patch("mrsiprep.workflows.participant.run_synthseg_parcellation", return_value=parcels), patch(
            "mrsiprep.workflows.participant.write_parcel_qc", return_value="parcel-qc"
        ), patch("mrsiprep.workflows.participant.write_parcel_qc_figures") as figures:
            result = P._step_synthseg_parcellation_qc(SimpleNamespace(), "01", "01", Path("raw_t1"), self._mrsi(), registration, _debug())
        self.assertEqual(figures.call_args.kwargs["t1_to_mni"], "mni_fwd")
        self.assertEqual(result, (parcels, "parcel-qc"))

    def test_without_t1_to_mni_passes_none_to_figures(self):
        registration = SimpleNamespace(mrsi_to_t1=SimpleNamespace(inverse="inv"), t1_to_mni=None)
        parcels = SimpleNamespace(atlas_t1="atlas_t1", atlas_mrsi="atlas_mrsi")
        with patch("mrsiprep.workflows.participant.run_synthseg_parcellation", return_value=parcels), patch(
            "mrsiprep.workflows.participant.write_parcel_qc", return_value="parcel-qc"
        ), patch("mrsiprep.workflows.participant.write_parcel_qc_figures") as figures:
            P._step_synthseg_parcellation_qc(SimpleNamespace(), "01", "01", Path("raw_t1"), self._mrsi(), registration, _debug())
        self.assertIsNone(figures.call_args.kwargs["t1_to_mni"])


class StepParcellationTests(unittest.TestCase):
    def test_mni_norm_returns_preliminary_parcels_unchanged(self):
        config = SimpleNamespace(processing_mode="mni-norm")
        preliminary = SimpleNamespace(atlas_t1="preliminary")
        with patch("mrsiprep.workflows.participant.run_parcellation_workflow") as run_fn, patch(
            "mrsiprep.workflows.participant.build_parcellation_qc_sections"
        ) as qc_fn:
            parcels, qc = P._step_parcellation(config, "01", "01", Path("raw_t1"), SimpleNamespace(reference="ref"), SimpleNamespace(registration_t1w="t1"), object(), preliminary, _debug())
        run_fn.assert_not_called()
        qc_fn.assert_not_called()
        self.assertIs(parcels, preliminary)
        self.assertIsNone(qc)

    def test_parc_con_runs_full_parcellation(self):
        config = SimpleNamespace(processing_mode="parc-con")
        preliminary = SimpleNamespace(atlas_t1="preliminary")
        final = SimpleNamespace(atlas_t1="final", labels="labels")
        with patch("mrsiprep.workflows.participant.run_parcellation_workflow", return_value=final) as run_fn, patch(
            "mrsiprep.workflows.participant.build_parcellation_qc_sections", return_value=["qc"]
        ) as qc_fn:
            parcels, qc = P._step_parcellation(
                config, "01", "01", Path("raw_t1"), SimpleNamespace(reference="ref"), SimpleNamespace(registration_t1w="t1"), "registration", preliminary, _debug()
            )
        run_fn.assert_called_once_with(config, "01", "01", "ref", "registration", raw_t1=Path("raw_t1"), t1_reference="t1")
        qc_fn.assert_called_once_with(config, "01", "01", Path("raw_t1"), "final", "labels")
        self.assertIs(parcels, final)
        self.assertEqual(qc, ["qc"])


class StepRegionalExtractionTests(unittest.TestCase):
    def _mrsi(self):
        return SimpleNamespace(qcmasks={}, snr_map=None, linewidth_map=None, crlb_maps={})

    def test_parc_con_with_tissue_passes_tissue_fractions(self):
        config = SimpleNamespace(processing_mode="parc-con")
        tissue = SimpleNamespace(mrsi={"GM": Path("gm")})
        with patch("mrsiprep.workflows.participant.extract_regional_metabolites", return_value="regional") as extract:
            regional = P._step_regional_extraction(config, "01", "01", {}, "parcels", self._mrsi(), tissue, _debug())
        self.assertEqual(extract.call_args.args[-1], {"GM": Path("gm")})
        self.assertEqual(regional, "regional")

    def test_parc_con_without_tissue_passes_empty_dict(self):
        config = SimpleNamespace(processing_mode="parc-con")
        with patch("mrsiprep.workflows.participant.extract_regional_metabolites", return_value="regional") as extract:
            P._step_regional_extraction(config, "01", "01", {}, "parcels", self._mrsi(), None, _debug())
        self.assertEqual(extract.call_args.args[-1], {})


class StepConnectivityTests(unittest.TestCase):
    def test_non_parc_con_mode_returns_empty_without_calling_anything(self):
        config = SimpleNamespace(processing_mode="mni-norm", write_connectivity=False)
        with patch("mrsiprep.workflows.participant.run_connectivity_workflow") as run_fn, patch(
            "mrsiprep.workflows.participant.build_connectivity_qc_sections"
        ) as qc_fn:
            result = P._step_connectivity(config, "01", "01", "regional", "parcels", {}, SimpleNamespace(), None, _debug())
        self.assertEqual(result, ({}, None))
        run_fn.assert_not_called()
        qc_fn.assert_not_called()

    def test_parc_con_with_tissue_passes_gm_fraction_path(self):
        config = SimpleNamespace(processing_mode="parc-con", write_connectivity=True)
        mrsi = SimpleNamespace(crlb_maps={}, brainmask=Path("mask"))
        tissue = SimpleNamespace(mrsi={"GM": Path("gm")})
        with patch(
            "mrsiprep.workflows.participant.run_connectivity_workflow", return_value={"matrix_tsv": Path("matrix.tsv")}
        ) as run_fn, patch("mrsiprep.workflows.participant.build_connectivity_qc_sections", return_value=["conn-qc"]) as qc_fn:
            connectivity, qc = P._step_connectivity(config, "01", "01", "regional", "parcels", {}, mrsi, tissue, _debug())
        self.assertEqual(run_fn.call_args.kwargs["gm_fraction_path"], Path("gm"))
        qc_fn.assert_called_once_with(config, "01", "01", Path("matrix.tsv"))
        self.assertEqual(connectivity, {"matrix_tsv": Path("matrix.tsv")})
        self.assertEqual(qc, ["conn-qc"])

    def test_parc_con_without_tissue_passes_none_gm_fraction_path(self):
        config = SimpleNamespace(processing_mode="parc-con", write_connectivity=False)
        mrsi = SimpleNamespace(crlb_maps={}, brainmask=Path("mask"))
        with patch("mrsiprep.workflows.participant.run_connectivity_workflow", return_value={}) as run_fn, patch(
            "mrsiprep.workflows.participant.build_connectivity_qc_sections"
        ):
            P._step_connectivity(config, "01", "01", "regional", "parcels", {}, mrsi, None, _debug())
        self.assertIsNone(run_fn.call_args.kwargs["gm_fraction_path"])


class StepMetprofilesTests(unittest.TestCase):
    def test_mni_norm_returns_none_without_calling(self):
        config = SimpleNamespace(processing_mode="mni-norm")
        with patch("mrsiprep.workflows.participant.export_metprofile_npz") as fn:
            result = P._step_metprofiles(config, "01", "01", {}, SimpleNamespace(), "parcels", "regional", SimpleNamespace())
        self.assertIsNone(result)
        fn.assert_not_called()

    def test_parc_con_exports_metprofiles(self):
        config = SimpleNamespace(processing_mode="parc-con")
        mrsi = SimpleNamespace(water_map=Path("water"))
        anat = SimpleNamespace(registration_mask=Path("mask"))
        with patch("mrsiprep.workflows.participant.export_metprofile_npz", return_value="npz-path") as fn:
            result = P._step_metprofiles(config, "01", "01", {"corrected": 1}, mrsi, "parcels", "regional", anat)
        fn.assert_called_once_with(config, "01", "01", {"corrected": 1}, Path("water"), "parcels", "regional", Path("mask"))
        self.assertEqual(result, "npz-path")


class StepReportsTests(unittest.TestCase):
    def test_stores_report_under_outputs(self):
        outputs = {"t1w": "x"}
        with patch("mrsiprep.workflows.participant.run_reports_workflow", return_value="report.html") as fn:
            result = P._step_reports(SimpleNamespace(), "01", "01", outputs, ["qc"], _debug())
        fn.assert_called_once_with(unittest.mock.ANY, "01", "01", outputs, ["qc"])
        self.assertEqual(result["report"], "report.html")
        self.assertEqual(result["t1w"], "x")


if __name__ == "__main__":
    unittest.main()
