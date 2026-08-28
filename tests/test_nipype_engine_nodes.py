"""Wiring tests for mrsiprep/workflows/nipype_engine/nodes.py.

Each step_*() function is a thin adapter: pull specific keys out of ctx,
call one function from mrsiprep.workflows.participant (or elsewhere), and
write the result back under new ctx key(s) -- without mutating the input
ctx dict in place. These tests mock the one call each step makes and
verify the ctx-key contract on both sides, since a renamed/reordered key
on one side of that contract without the other would not be caught by
mrsiprep.workflows.nipype_engine's own structural tests (which check the
STEP_SEQUENCE graph shape, not per-step argument wiring).
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mrsiprep.parcellation.base import ParcellationResult
from mrsiprep.workflows.nipype_engine import nodes as N

_SUBJECT, _SESSION = "01", "01"


def _fake_config(**overrides):
    """Minimal config stand-in. Every step_*() that builds a Debug(...)
    accesses config.verbose for real (Debug itself is not mocked), and
    step_prepare additionally accesses config.bids_dir/bids_filters (its
    arguments are evaluated eagerly even though BIDSLayout itself is
    mocked) -- a bare object() fails both with AttributeError."""
    defaults = dict(verbose=0, bids_dir="bids", bids_filters=None)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class StepPrepareTests(unittest.TestCase):
    def test_seeds_ctx_and_does_not_mutate_input(self):
        inputs = SimpleNamespace()
        raw_t1 = "raw_t1.nii.gz"
        with patch("mrsiprep.io.validators.validate_recording", return_value=("t1.nii.gz", inputs)), patch(
            "mrsiprep.io.bids.BIDSLayout"
        ) as layout_cls:
            layout_cls.from_config.return_value = layout_cls.return_value
            layout_cls.return_value.raw_t1.return_value = raw_t1
            original = {}
            result = N.step_prepare(_fake_config(), _SUBJECT, _SESSION, original)

        self.assertEqual(original, {})
        self.assertEqual(result["t1_path"], "t1.nii.gz")
        self.assertIs(result["inputs"], inputs)
        self.assertEqual(result["raw_t1"], raw_t1)

    def test_raises_when_no_raw_t1(self):
        with patch("mrsiprep.io.validators.validate_recording", return_value=("t1.nii.gz", SimpleNamespace())), patch(
            "mrsiprep.io.bids.BIDSLayout"
        ) as layout_cls:
            layout_cls.from_config.return_value = layout_cls.return_value
            layout_cls.return_value.raw_t1.return_value = None
            with self.assertRaisesRegex(FileNotFoundError, "Missing raw T1w"):
                N.step_prepare(_fake_config(), _SUBJECT, _SESSION, {})


class StepTissueSegTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"raw_t1": "raw", "t1_path": "t1"}
        with patch(
            "mrsiprep.workflows.participant._step_tissue_segmentation", return_value=("new_t1", "tissue", "p3", "mask")
        ) as step:
            result = N.step_tissue_seg(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once()
        self.assertEqual(step.call_args[0][3], "raw")
        self.assertEqual(step.call_args[0][4], "t1")
        self.assertEqual(ctx, {"raw_t1": "raw", "t1_path": "t1"})
        self.assertEqual(result["t1_path"], "new_t1")
        self.assertEqual(result["precomputed_tissue_t1"], "tissue")
        self.assertEqual(result["p3_override"], "p3")
        self.assertEqual(result["brain_mask_override"], "mask")


class StepAnatTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"t1_path": "t1", "p3_override": "p3", "brain_mask_override": "mask"}
        with patch("mrsiprep.workflows.participant._step_anatomical_prep", return_value="anat_result") as step:
            result = N.step_anat(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "t1", "p3", "mask", unittest.mock.ANY)
        self.assertEqual(result["anat"], "anat_result")
        self.assertNotIn("anat", ctx)


class StepMrsiTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"inputs": "inputs_obj"}
        with patch(
            "mrsiprep.workflows.participant._step_mrsi_preprocessing", return_value=("mrsi_obj", "raw_qc", "preproc_qc", "t1corr_qc")
        ) as step:
            result = N.step_mrsi(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertEqual(step.call_args[0][3], "inputs_obj")
        self.assertEqual(result["mrsi"], "mrsi_obj")
        self.assertEqual(result["qc_sections_mrsi_raw"], "raw_qc")
        self.assertEqual(result["qc_sections_mrsi_preproc"], "preproc_qc")
        self.assertEqual(result["qc_sections_t1_correction"], "t1corr_qc")


class StepRegistrationTests(unittest.TestCase):
    def test_wires_ctx_in_and_out_including_optional_subject_template(self):
        ctx = {"mrsi": "mrsi_obj", "anat": "anat_obj", "subject_template": "template_obj"}
        with patch("mrsiprep.workflows.participant._step_registration", return_value="registration_obj") as step:
            result = N.step_registration(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertEqual(step.call_args[0][3], "mrsi_obj")
        self.assertEqual(step.call_args[0][4], "anat_obj")
        self.assertEqual(step.call_args.kwargs["subject_template"], "template_obj")
        self.assertEqual(result["registration"], "registration_obj")

    def test_subject_template_defaults_to_none_when_absent(self):
        ctx = {"mrsi": "mrsi_obj", "anat": "anat_obj"}
        with patch("mrsiprep.workflows.participant._step_registration", return_value="registration_obj") as step:
            N.step_registration(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertIsNone(step.call_args.kwargs["subject_template"])


class StepTissueProbmapsTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"anat": "anat_obj", "mrsi": "mrsi_obj", "registration": "reg_obj", "precomputed_tissue_t1": "precomp"}
        with patch("mrsiprep.workflows.participant._step_tissue_probmaps", return_value="tissue_obj") as step:
            result = N.step_tissue_probmaps(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "anat_obj", "mrsi_obj", "reg_obj", "precomp", unittest.mock.ANY)
        self.assertEqual(result["tissue"], "tissue_obj")


class StepTissueQcTests(unittest.TestCase):
    def test_uses_native_labels_when_file_exists(self):
        candidate = MagicMock()
        candidate.exists.return_value = True
        tissue = SimpleNamespace(t1="tissue_t1")
        ctx = {"raw_t1": "raw", "tissue": tissue}
        with patch("mrsiprep.tissue.synthseg_fast.synthseg_native_labels_path", return_value=candidate), patch(
            "mrsiprep.reports.tissue.build_tissue_qc_sections", return_value="qc"
        ) as build:
            result = N.step_tissue_qc(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertEqual(build.call_args[0][3], "raw")
        self.assertIs(build.call_args[0][4], candidate)
        self.assertEqual(build.call_args[0][5], "tissue_t1")
        self.assertEqual(result["qc_sections_tissue"], "qc")

    def test_dseg_is_none_when_file_missing(self):
        candidate = MagicMock()
        candidate.exists.return_value = False
        ctx = {"raw_t1": "raw", "tissue": None}
        with patch("mrsiprep.tissue.synthseg_fast.synthseg_native_labels_path", return_value=candidate), patch(
            "mrsiprep.reports.tissue.build_tissue_qc_sections", return_value="qc"
        ) as build:
            N.step_tissue_qc(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertIsNone(build.call_args[0][4])
        self.assertIsNone(build.call_args[0][5])  # tissue is None -> no .t1 access


class StepPvcTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"mrsi": "mrsi_obj", "tissue": "tissue_obj"}
        with patch("mrsiprep.workflows.participant._step_pvc", return_value=("corrected", "tissue_4d")) as step, patch(
            "mrsiprep.reports.mrsi_pvc_overview.build_mrsi_pvc_sections", return_value=["pvc_qc"]
        ):
            result = N.step_pvc(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertEqual(step.call_args[0][3], "mrsi_obj")
        self.assertEqual(step.call_args[0][4], "tissue_obj")
        self.assertEqual(result["corrected_maps"], "corrected")
        self.assertEqual(result["tissue_4d"], "tissue_4d")

    def test_pvc_qc_sections_are_built_when_pvc_ran(self):
        ctx = {"mrsi": SimpleNamespace(preproc_maps={"CrPCr": Path("/x/pre.nii.gz")}), "tissue": "tissue_obj"}
        corrected = {"CrPCr": Path("/x/pvc.nii.gz")}
        with patch("mrsiprep.workflows.participant._step_pvc", return_value=(corrected, "tissue_4d")), patch(
            "mrsiprep.reports.mrsi_pvc_overview.build_mrsi_pvc_sections", return_value=["pvc_qc"]
        ) as build:
            result = N.step_pvc(_fake_config(), _SUBJECT, _SESSION, ctx)
        build.assert_called_once()
        self.assertEqual(result["qc_sections_mrsi_pvc"], ["pvc_qc"])

    def test_no_pvc_leaves_the_tab_out_entirely(self):
        """--no-pvc returns the preproc maps unchanged, so a PVC tab would show
        images identical to the ones already in MRSI Raw QC."""
        preproc = {"CrPCr": Path("/x/pre.nii.gz")}
        ctx = {"mrsi": SimpleNamespace(preproc_maps=preproc), "tissue": None}
        with patch("mrsiprep.workflows.participant._step_pvc", return_value=(preproc, None)), patch(
            "mrsiprep.reports.mrsi_pvc_overview.build_mrsi_pvc_sections"
        ) as build:
            result = N.step_pvc(_fake_config(), _SUBJECT, _SESSION, ctx)
        build.assert_not_called()
        self.assertIsNone(result["qc_sections_mrsi_pvc"])


class StepResamplingTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"anat": "anat_obj", "mrsi": "mrsi_obj", "registration": "reg_obj", "corrected_maps": "corrected", "raw_t1": "raw"}
        with patch("mrsiprep.workflows.participant._step_resampling", return_value=("transformed", "t1w_qc", "mni_qc")) as step:
            result = N.step_resampling(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(
            unittest.mock.ANY, _SUBJECT, _SESSION, "anat_obj", "mrsi_obj", "reg_obj", "corrected", "raw", unittest.mock.ANY
        )
        self.assertEqual(result["transformed"], "transformed")
        self.assertEqual(result["qc_sections_t1w_alignment"], "t1w_qc")
        self.assertEqual(result["qc_sections_mni_alignment"], "mni_qc")


class StepLeakageQcTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"anat": "anat_obj", "transformed": "transformed_obj"}
        with patch("mrsiprep.workflows.participant._step_leakage_qc", return_value="leakage") as step:
            result = N.step_leakage_qc(_fake_config(), _SUBJECT, _SESSION, ctx)

        self.assertEqual(step.call_args[0][3], "anat_obj")
        self.assertEqual(step.call_args[0][4], "transformed_obj")
        self.assertEqual(result["leakage_qc"], "leakage")


class StepSynthsegParcQcTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"raw_t1": "raw", "mrsi": "mrsi_obj", "registration": "reg_obj"}
        with patch("mrsiprep.workflows.participant._step_synthseg_parcellation_qc", return_value=("prelim", "parcel_qc")) as step:
            result = N.step_synthseg_parc_qc(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "raw", "mrsi_obj", "reg_obj", unittest.mock.ANY)
        self.assertEqual(result["preliminary_parcels"], "prelim")
        self.assertEqual(result["parcel_qc"], "parcel_qc")


class StepParcellationTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"raw_t1": "raw", "mrsi": "mrsi_obj", "anat": "anat_obj", "registration": "reg_obj", "preliminary_parcels": "prelim"}
        with patch("mrsiprep.workflows.participant._step_parcellation", return_value=("parcels", "parc_qc")) as step:
            result = N.step_parcellation(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "raw", "mrsi_obj", "anat_obj", "reg_obj", "prelim", unittest.mock.ANY)
        self.assertEqual(result["parcels"], "parcels")
        self.assertEqual(result["qc_sections_parcellation"], "parc_qc")


class StepRegionalTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"corrected_maps": "corrected", "parcels": "parcels_obj", "mrsi": "mrsi_obj", "tissue": "tissue_obj"}
        with patch("mrsiprep.workflows.participant._step_regional_extraction", return_value="regional") as step:
            result = N.step_regional(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "corrected", "parcels_obj", "mrsi_obj", "tissue_obj", unittest.mock.ANY)
        self.assertEqual(result["regional"], "regional")


class StepConnectivityTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"regional": "regional_obj", "parcels": "parcels_obj", "corrected_maps": "corrected", "mrsi": "mrsi_obj", "tissue": "tissue_obj"}
        with patch("mrsiprep.workflows.participant._step_connectivity", return_value=("connectivity", "conn_qc")) as step:
            result = N.step_connectivity(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(
            unittest.mock.ANY, _SUBJECT, _SESSION, "regional_obj", "parcels_obj", "corrected", "mrsi_obj", "tissue_obj", unittest.mock.ANY
        )
        self.assertEqual(result["connectivity"], "connectivity")
        self.assertEqual(result["qc_sections_connectivity"], "conn_qc")


class StepMetprofilesTests(unittest.TestCase):
    def test_wires_ctx_in_and_out(self):
        ctx = {"corrected_maps": "corrected", "mrsi": "mrsi_obj", "parcels": "parcels_obj", "regional": "regional_obj", "anat": "anat_obj"}
        with patch("mrsiprep.workflows.participant._step_metprofiles", return_value="metprofiles_result") as step:
            result = N.step_metprofiles(_fake_config(), _SUBJECT, _SESSION, ctx)

        step.assert_called_once_with(unittest.mock.ANY, _SUBJECT, _SESSION, "corrected", "mrsi_obj", "parcels_obj", "regional_obj", "anat_obj")
        self.assertEqual(result["metprofiles"], "metprofiles_result")


class StepReportsTests(unittest.TestCase):
    def _ctx(self, t1_correction_provenance=None):
        anat = SimpleNamespace(t1w="t1w_path", registration_t1w="reg_t1w_path")
        mrsi = SimpleNamespace(reference="ref_map", qc_summary="qc_sum", t1_correction_provenance=t1_correction_provenance)
        parcels = ParcellationResult(
            atlas_mrsi="atlas_mrsi_final", labels="labels", atlas_name="chimeraA", scale="scale3"
        )
        preliminary_parcels = SimpleNamespace(atlas_mrsi="atlas_mrsi_prelim")
        pid = parcels.parcellation_id
        return {
            "anat": anat,
            "mrsi": mrsi,
            # parcels is a list; the per-parcellation results are keyed by id.
            "parcels": [parcels],
            "parcel_qc": "parcel_qc_obj",
            "leakage_qc": "leakage_qc_obj",
            "tissue_4d": "tissue_4d_obj",
            "preliminary_parcels": preliminary_parcels,
            "regional": {pid: "regional_obj"},
            "metprofiles": {pid: "metprofiles_obj"},
            "connectivity": {pid: "connectivity_obj"},
            "transformed": "transformed_obj",
            "qc_sections_tissue": "tissue_qc",
            "qc_sections_mrsi_raw": "mrsi_raw_qc",
            "qc_sections_mrsi_preproc": "mrsi_preproc_qc",
            "qc_sections_t1_correction": "t1corr_qc",
            "qc_sections_t1w_alignment": "t1w_align_qc",
            "qc_sections_mni_alignment": "mni_align_qc",
            "qc_sections_parcellation": "parc_qc",
            "qc_sections_connectivity": "conn_qc",
        }

    def test_assembles_outputs_and_writes_provenance(self):
        ctx = self._ctx()
        with patch("mrsiprep.workflows.participant._step_reports", side_effect=lambda cfg, s, ses, outputs, qc, debug: outputs) as step_reports, \
            patch("mrsiprep.utils.provenance.write_provenance", return_value="provenance_path") as write_prov, \
            patch("mrsiprep.io.naming.provenance_derivative", return_value="provenance_derivative_path"), \
            patch("mrsiprep.reports.runtime_overview.build_runtime_qc_sections", return_value="runtime_qc"), \
            patch("mrsiprep.utils.debug.collect_timings", return_value=[]):
            config = SimpleNamespace(verbose=0, derivative_dir="deriv", t1_correction="none", t1_correction_water_status="unknown")
            result = N.step_reports(config, _SUBJECT, _SESSION, ctx)

        outputs = step_reports.call_args[0][3]
        self.assertEqual(outputs["t1w"], "t1w_path")
        self.assertEqual(outputs["atlas_mrsi"], "atlas_mrsi_final")
        self.assertEqual(outputs["preliminary_atlas_mrsi"], "atlas_mrsi_prelim")
        # Singular keys still resolve to the first parcellation, so existing
        # report/provenance consumers keep working unchanged.
        self.assertEqual(outputs["regional_table"], "regional_obj")
        self.assertEqual(outputs["metprofiles"], "metprofiles_obj")
        self.assertEqual(outputs["connectivity"], "connectivity_obj")
        self.assertEqual(
            outputs["parcellations"],
            [{
                "id": "chimeraA-scale3", "atlas_name": "chimeraA", "scale": "scale3", "grow": None,
                "atlas_mrsi": "atlas_mrsi_final", "regional_table": "regional_obj",
                "metprofiles": "metprofiles_obj", "connectivity": "connectivity_obj",
            }],
        )
        qc_sections = step_reports.call_args[0][4]
        self.assertEqual(qc_sections["runtime"], "runtime_qc")

        write_prov.assert_called_once()
        provenance_payload = write_prov.call_args[0][2]
        self.assertIsNone(provenance_payload["t1_correction"])  # no T1 correction ran
        self.assertEqual(result["outputs"]["provenance"], "provenance_path")

    def test_provenance_includes_t1_correction_when_present(self):
        ctx = self._ctx(t1_correction_provenance={"CrPCr": {"factor": 0.9}})
        with patch("mrsiprep.workflows.participant._step_reports", side_effect=lambda cfg, s, ses, outputs, qc, debug: outputs), \
            patch("mrsiprep.utils.provenance.write_provenance", return_value="provenance_path") as write_prov, \
            patch("mrsiprep.io.naming.provenance_derivative", return_value="provenance_derivative_path"), \
            patch("mrsiprep.reports.runtime_overview.build_runtime_qc_sections", return_value="runtime_qc"), \
            patch("mrsiprep.utils.debug.collect_timings", return_value=[]):
            config = SimpleNamespace(verbose=0, derivative_dir="deriv", t1_correction="literature", t1_correction_water_status="corrected")
            N.step_reports(config, _SUBJECT, _SESSION, ctx)

        provenance_payload = write_prov.call_args[0][2]
        self.assertEqual(provenance_payload["t1_correction"]["mode"], "literature")
        self.assertEqual(provenance_payload["t1_correction"]["per_metabolite"], {"CrPCr": {"factor": 0.9}})


class StepSequenceStructureTests(unittest.TestCase):
    def test_every_step_is_a_two_tuple_of_name_and_callable(self):
        for entry in N.STEP_SEQUENCE:
            self.assertEqual(len(entry), 2)
            name, fn = entry
            self.assertIsInstance(name, str)
            self.assertTrue(callable(fn))

    def test_step_names_are_unique(self):
        names = [name for name, _ in N.STEP_SEQUENCE]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
