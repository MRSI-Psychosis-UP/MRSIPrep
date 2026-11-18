import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.io.derivatives import init_derivative
from mrsiprep.workflows.connectivity import run_connectivity_workflow
from mrsiprep.workflows.parcellation import run_parcellation_workflow
from mrsiprep.workflows.tissue import TissueResult, run_tissue_workflow


def _registration(mrsi_inverse="MRSI_INV", t1_to_mni_inverse="MNI_INV"):
    return SimpleNamespace(
        mrsi_to_t1=SimpleNamespace(inverse=mrsi_inverse),
        t1_to_mni=None if t1_to_mni_inverse is None else SimpleNamespace(inverse=t1_to_mni_inverse),
    )


class RunParcellationWorkflowTests(unittest.TestCase):
    def test_synthseg_mode_dispatches_with_the_inverse_mrsi_transform(self):
        config = SimpleNamespace(parcellation_mode="synthseg")

        with patch("mrsiprep.workflows.parcellation.run_synthseg_parcellation", return_value="SYNTH") as run:
            result = run_parcellation_workflow(
                config, "S001", "V1", "REF", _registration(), raw_t1="RAWT1"
            )

        # Always a list, even for the single synthseg parcellation.
        self.assertEqual(result, ["SYNTH"])
        self.assertEqual(run.call_args.args[3], "RAWT1")
        self.assertEqual(run.call_args.args[5], "MRSI_INV")

    def test_synthseg_without_raw_t1_raises(self):
        config = SimpleNamespace(parcellation_mode="synthseg")

        with patch("mrsiprep.workflows.parcellation.run_synthseg_parcellation") as run:
            with self.assertRaisesRegex(FileNotFoundError, "SynthSeg parcellation requires a raw T1w"):
                run_parcellation_workflow(config, "S001", "V1", "REF", _registration(), raw_t1=None)

        run.assert_not_called()

    def test_chimera_mode_dispatches_with_the_inverse_mrsi_transform(self):
        config = SimpleNamespace(parcellation_mode="chimera")

        with patch("mrsiprep.workflows.parcellation.run_chimera_parcellation", return_value="CHIM") as run:
            result = run_parcellation_workflow(config, "S001", "V1", "REF", _registration())

        self.assertEqual(result, "CHIM")   # backend already returns a list
        self.assertEqual(run.call_args.args[4], "MRSI_INV")

    def test_chimera_does_not_require_raw_t1_at_this_layer(self):
        # chimera_native resolves the T1w itself from the BIDS layout.
        config = SimpleNamespace(parcellation_mode="chimera")

        with patch("mrsiprep.workflows.parcellation.run_chimera_parcellation", return_value="CHIM"):
            self.assertEqual(
                run_parcellation_workflow(config, "S001", "V1", "REF", _registration(), raw_t1=None), "CHIM"
            )

    def test_atlas_mode_passes_both_inverse_transforms_in_order(self):
        config = SimpleNamespace(parcellation_mode="atlas")

        with patch("mrsiprep.workflows.parcellation.run_mni_parcellation", return_value="ATLAS") as run:
            result = run_parcellation_workflow(
                config, "S001", "V1", "REF", _registration(), t1_reference="T1REF"
            )

        self.assertEqual(result, "ATLAS")
        self.assertEqual(run.call_args.args[4], "T1REF")
        # MNI->T1w first, then T1w->MRSI.
        self.assertEqual(run.call_args.args[5], "MNI_INV")
        self.assertEqual(run.call_args.args[6], "MRSI_INV")

    def test_atlas_mode_without_mni_normalization_raises_runtime_error(self):
        config = SimpleNamespace(parcellation_mode="atlas")

        with patch("mrsiprep.workflows.parcellation.run_mni_parcellation") as run:
            with self.assertRaisesRegex(RuntimeError, "requires T1-to-MNI normalization"):
                run_parcellation_workflow(
                    config, "S001", "V1", "REF", _registration(t1_to_mni_inverse=None), t1_reference="T1REF"
                )

        run.assert_not_called()

    def test_atlas_mode_without_t1_reference_raises_value_error(self):
        config = SimpleNamespace(parcellation_mode="atlas")

        with patch("mrsiprep.workflows.parcellation.run_mni_parcellation") as run:
            with self.assertRaisesRegex(ValueError, "requires a T1 reference image"):
                run_parcellation_workflow(config, "S001", "V1", "REF", _registration(), t1_reference=None)

        run.assert_not_called()

    def test_unsupported_mode_raises_naming_the_value(self):
        config = SimpleNamespace(parcellation_mode="mni")  # the pre-rename value

        with self.assertRaisesRegex(ValueError, "Unsupported parcellation mode: mni"):
            run_parcellation_workflow(config, "S001", "V1", "REF", _registration())


class RunConnectivityWorkflowTests(unittest.TestCase):
    def _parcels(self):
        return SimpleNamespace(atlas_name="testatlas", atlas_mrsi="ATLAS_MRSI", scale="3")

    def _export_profiles(self, **kwargs):
        return patch(
            "mrsiprep.workflows.connectivity.export_metabolic_profiles",
            return_value=("PROFILES", "PROFILE_NPZ", "TABLE"),
            **kwargs,
        )

    def test_profiles_always_run_and_are_returned(self):
        config = SimpleNamespace(write_connectivity=False)

        with self._export_profiles() as profiles_mock, patch(
            "mrsiprep.workflows.connectivity.export_connectivity"
        ) as conn_mock:
            outputs = run_connectivity_workflow(
                config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK"
            )

        profiles_mock.assert_called_once()
        conn_mock.assert_not_called()
        self.assertEqual(outputs, {"profiles": "PROFILE_NPZ"})

    def test_connectivity_matrix_is_added_only_when_opted_in(self):
        config = SimpleNamespace(write_connectivity=True)

        with self._export_profiles(), patch(
            "mrsiprep.workflows.connectivity.export_connectivity",
            return_value={"matrix_npz": "M", "nodes": "N", "edges": "E"},
        ) as conn_mock:
            outputs = run_connectivity_workflow(
                config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK"
            )

        conn_mock.assert_called_once()
        self.assertEqual(outputs["profiles"], "PROFILE_NPZ")
        for key in ("matrix_npz", "nodes", "edges"):
            self.assertIn(key, outputs)

    def test_connectivity_reuses_the_already_computed_profiles(self):
        config = SimpleNamespace(write_connectivity=True)

        with self._export_profiles(), patch(
            "mrsiprep.workflows.connectivity.export_connectivity", return_value={}
        ) as conn_mock:
            run_connectivity_workflow(config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK")

        # The profiles object and its table are handed straight through
        # rather than recomputed inside export_connectivity.
        self.assertEqual(conn_mock.call_args.args[3], "PROFILES")
        self.assertEqual(conn_mock.call_args.args[4], "TABLE")

    def test_atlas_identity_is_forwarded_to_both_exports(self):
        config = SimpleNamespace(write_connectivity=True)

        with self._export_profiles() as profiles_mock, patch(
            "mrsiprep.workflows.connectivity.export_connectivity", return_value={}
        ) as conn_mock:
            run_connectivity_workflow(config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK")

        self.assertEqual(profiles_mock.call_args.args[4], "testatlas")
        self.assertEqual(profiles_mock.call_args.kwargs["scale"], "3")
        self.assertEqual(conn_mock.call_args.args[5], "testatlas")
        self.assertEqual(conn_mock.call_args.kwargs["scale"], "3")

    def test_gm_fraction_path_is_forwarded_when_given(self):
        config = SimpleNamespace(write_connectivity=False)

        with self._export_profiles() as profiles_mock:
            run_connectivity_workflow(
                config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK", gm_fraction_path="GM"
            )

        self.assertEqual(profiles_mock.call_args.kwargs["gm_fraction_path"], "GM")

    def test_gm_fraction_defaults_to_none(self):
        config = SimpleNamespace(write_connectivity=False)

        with self._export_profiles() as profiles_mock:
            run_connectivity_workflow(config, "S001", "V1", "TABLE_IN", self._parcels(), {}, {}, "MASK")

        self.assertIsNone(profiles_mock.call_args.kwargs["gm_fraction_path"])


class RunTissueWorkflowTests(unittest.TestCase):
    def _resample(self, **kwargs):
        return patch(
            "mrsiprep.workflows.tissue.resample_tissue_to_mrsi", return_value={"GM": "GM_MRSI"}, **kwargs
        )

    def test_precomputed_maps_skip_segmentation_entirely(self):
        config = SimpleNamespace(tissue_backend="synthseg-fast")
        precomputed = {"GM": "GM_T1"}

        with self._resample(), patch("mrsiprep.workflows.tissue.segment_t1_synthseg_fast") as seg, patch(
            "mrsiprep.workflows.tissue.load_existing_cat12"
        ) as cat12:
            result = run_tissue_workflow(
                config, "S001", "V1", "T1", None, "REF", [], precomputed_tissue_t1=precomputed
            )

        seg.assert_not_called()
        cat12.assert_not_called()
        self.assertEqual(result.t1, precomputed)

    def test_synthseg_fast_backend_segments(self):
        config = SimpleNamespace(tissue_backend="synthseg-fast")

        with self._resample(), patch(
            "mrsiprep.workflows.tissue.segment_t1_synthseg_fast", return_value={"GM": "GM_T1"}
        ) as seg:
            result = run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])

        seg.assert_called_once()
        self.assertEqual(seg.call_args.args[3], "T1")
        self.assertEqual(result.t1, {"GM": "GM_T1"})

    def test_existing_backend_loads_and_copies_cat12_maps(self):
        config = SimpleNamespace(tissue_backend="existing")

        with self._resample(), patch(
            "mrsiprep.workflows.tissue.load_existing_cat12", return_value={"GM": "GM_SRC"}
        ) as load, patch(
            "mrsiprep.workflows.tissue.copy_tissue_to_derivatives", return_value={"GM": "GM_COPY"}
        ) as copy:
            result = run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])

        load.assert_called_once()
        copy.assert_called_once()
        self.assertEqual(result.t1, {"GM": "GM_COPY"})

    def test_unsupported_backend_raises_naming_the_value(self):
        config = SimpleNamespace(tissue_backend="bogus")

        with self.assertRaisesRegex(ValueError, "Unsupported tissue backend: bogus"):
            run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])

    def test_unsupported_backend_is_bypassed_by_precomputed_maps(self):
        # 'none' never reaches the backend dispatch when maps are supplied.
        config = SimpleNamespace(tissue_backend="none")

        with self._resample():
            result = run_tissue_workflow(
                config, "S001", "V1", "T1", None, "REF", [], precomputed_tissue_t1={"GM": "GM_T1"}
            )

        self.assertEqual(result.t1, {"GM": "GM_T1"})

    def test_result_carries_both_spaces(self):
        config = SimpleNamespace(tissue_backend="synthseg-fast")

        with self._resample(), patch(
            "mrsiprep.workflows.tissue.segment_t1_synthseg_fast", return_value={"GM": "GM_T1"}
        ):
            result = run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])

        self.assertIsInstance(result, TissueResult)
        self.assertEqual(result.t1, {"GM": "GM_T1"})
        self.assertEqual(result.mrsi, {"GM": "GM_MRSI"})

    def test_resampling_receives_the_segmented_maps_and_transforms(self):
        config = SimpleNamespace(tissue_backend="synthseg-fast")
        transforms = ["XFM"]

        with self._resample() as resample, patch(
            "mrsiprep.workflows.tissue.segment_t1_synthseg_fast", return_value={"GM": "GM_T1"}
        ):
            run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", transforms)

        self.assertEqual(resample.call_args.args[3], {"GM": "GM_T1"})
        self.assertEqual(resample.call_args.args[4], "REF")
        self.assertEqual(resample.call_args.args[5], transforms)


class InitDerivativeTests(unittest.TestCase):
    def test_creates_the_root_and_a_dataset_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "derivatives"

            result = init_derivative(root)

            self.assertEqual(result, root)
            self.assertTrue(root.is_dir())
            self.assertTrue((root / "dataset_description.json").exists())

    def test_description_declares_a_bids_derivative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = init_derivative(Path(tmpdir) / "derivatives")

            payload = json.loads((root / "dataset_description.json").read_text(encoding="utf-8"))

            self.assertEqual(payload["DatasetType"], "derivative")
            self.assertEqual(payload["Name"], "MRSIPrep derivatives")
            self.assertEqual(payload["GeneratedBy"], [{"Name": "MRSIPrep"}])
            self.assertIn("BIDSVersion", payload)

    def test_nested_roots_are_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = init_derivative(Path(tmpdir) / "a" / "b" / "c")
            self.assertTrue(root.is_dir())

    def test_existing_description_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "derivatives"
            init_derivative(root)
            desc = root / "dataset_description.json"
            desc.write_text('{"Name": "hand-edited"}', encoding="utf-8")

            init_derivative(root)

            self.assertEqual(json.loads(desc.read_text(encoding="utf-8"))["Name"], "hand-edited")

    def test_accepts_a_string_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = init_derivative(str(Path(tmpdir) / "derivatives"))
            self.assertTrue(Path(result).is_dir())

    def test_is_idempotent_on_an_existing_tree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "derivatives"
            self.assertEqual(init_derivative(root), init_derivative(root))


if __name__ == "__main__":
    unittest.main()
