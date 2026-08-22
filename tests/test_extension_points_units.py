"""Guards on the extension points contributors are meant to extend.

These exist so the registries in docs/extending.md stay real: if someone
renames or removes one, the recipe in the docs breaks and so does a test.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mrsiprep.workflows.parcellation import PARCELLATION_BACKENDS, run_parcellation_workflow
from mrsiprep.workflows.tissue import TISSUE_BACKENDS, run_tissue_workflow


class TissueBackendRegistryTests(unittest.TestCase):
    def test_registry_covers_the_cli_choices(self):
        # 'none' is deliberately absent: it means "no segmentation at all"
        # and is handled by config forcing --no-pvc, not by a backend.
        self.assertEqual(set(TISSUE_BACKENDS), {"existing", "synthseg-fast"})

    def test_every_entry_is_callable(self):
        for name, fn in TISSUE_BACKENDS.items():
            self.assertTrue(callable(fn), msg=name)

    def test_unknown_backend_error_lists_the_registered_ones(self):
        config = SimpleNamespace(tissue_backend="bogus")
        with self.assertRaises(ValueError) as ctx:
            run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])
        message = str(ctx.exception)
        self.assertIn("bogus", message)
        for name in TISSUE_BACKENDS:
            self.assertIn(name, message)

    def test_a_newly_registered_backend_is_dispatched_without_touching_dispatch(self):
        # The whole point of the registry: adding an entry is enough.
        calls = []

        def _fake_backend(_config, subject, session, t1_path):
            calls.append((subject, session, t1_path))
            return {"GM": "gm.nii.gz"}

        config = SimpleNamespace(tissue_backend="contrib-backend")
        with patch.dict(TISSUE_BACKENDS, {"contrib-backend": _fake_backend}), patch(
            "mrsiprep.workflows.tissue.resample_tissue_to_mrsi", return_value={"GM": "gm_mrsi.nii.gz"}
        ):
            result = run_tissue_workflow(config, "S001", "V1", "T1", None, "REF", [])

        self.assertEqual(calls, [("S001", "V1", "T1")])
        self.assertEqual(result.t1, {"GM": "gm.nii.gz"})


class ParcellationBackendRegistryTests(unittest.TestCase):
    def test_registry_covers_the_cli_choices(self):
        self.assertEqual(set(PARCELLATION_BACKENDS), {"synthseg", "chimera", "atlas"})

    def test_every_entry_is_callable(self):
        for name, fn in PARCELLATION_BACKENDS.items():
            self.assertTrue(callable(fn), msg=name)

    def test_unknown_mode_error_lists_the_registered_ones(self):
        config = SimpleNamespace(parcellation_mode="mni")  # the pre-rename value
        with self.assertRaises(ValueError) as ctx:
            run_parcellation_workflow(config, "S001", "V1", "REF", SimpleNamespace())
        message = str(ctx.exception)
        self.assertIn("mni", message)
        for name in PARCELLATION_BACKENDS:
            self.assertIn(name, message)

    def test_a_newly_registered_backend_is_dispatched(self):
        config = SimpleNamespace(parcellation_mode="contrib-parc")
        with patch.dict(PARCELLATION_BACKENDS, {"contrib-parc": lambda *args: ["PARCELS"]}):
            result = run_parcellation_workflow(config, "S001", "V1", "REF", SimpleNamespace())
        self.assertEqual(result, ["PARCELS"])


class ParticipantImportSurfaceTests(unittest.TestCase):
    """participant.py was split into preflight.py/steps.py; the names it used
    to expose must keep resolving, since nipype_engine.nodes and existing
    callers import them from there."""

    def test_step_functions_are_still_importable_from_participant(self):
        from mrsiprep.workflows import participant as P

        for name in (
            "_step_tissue_segmentation", "_step_anatomical_prep", "_step_mrsi_preprocessing",
            "_step_registration", "_step_tissue_probmaps", "_step_pvc", "_step_resampling",
            "_step_leakage_qc", "_step_synthseg_parcellation_qc", "_step_parcellation",
            "_step_regional_extraction", "_step_connectivity", "_step_metprofiles",
            "_step_reports", "_validate_backend_inputs",
        ):
            self.assertTrue(hasattr(P, name), msg=name)

    def test_preflight_helpers_are_still_importable_from_participant(self):
        from mrsiprep.workflows import participant as P

        for name in (
            "RecordingStatus", "_gather_input_availability", "_render_preflight_table",
            "_preflight_freesurfer_status", "_preflight_missing_items", "_PREFLIGHT_CHECK_MARK",
        ):
            self.assertTrue(hasattr(P, name), msg=name)

    def test_nipype_nodes_still_resolve_the_steps(self):
        # The concrete consumer that would break on a bad split.
        from mrsiprep.workflows.nipype_engine import nodes

        self.assertTrue(nodes.STEP_SEQUENCE)


if __name__ == "__main__":
    unittest.main()
