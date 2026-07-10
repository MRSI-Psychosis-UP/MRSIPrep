import ast
import builtins
import tempfile
import unittest
from pathlib import Path

from mrsiprep.config.settings import MRSIPrepConfig
from mrsiprep.workflows.nipype_engine.build import TERMINAL_NODE, build_recording_workflow, recording_base_dir
from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE


def _cfg(**over):
    d = tempfile.mkdtemp()
    base = dict(bids_dir=d, output_dir=str(Path(d) / "out"), analysis_level="participant", metabolites=["CrPCr"], ref_met="CrPCr")
    base.update(over)
    return MRSIPrepConfig(**base)


class NipypeEngineBuildTests(unittest.TestCase):
    def test_workflow_is_a_linear_chain_mirroring_step_sequence(self):
        wf = build_recording_workflow(_cfg(), "S001", "V1")
        names = sorted(n.name for n in wf._graph.nodes())
        self.assertEqual(names, sorted(n for n, _ in STEP_SEQUENCE))
        self.assertEqual(len(names), len(STEP_SEQUENCE))
        edges = {(a.name, b.name) for a, b in wf._graph.edges()}
        order = [n for n, _ in STEP_SEQUENCE]
        for a, b in zip(order, order[1:]):
            self.assertIn((a, b), edges)
        self.assertEqual(len(edges), len(order) - 1)

    def test_terminal_node_is_reports(self):
        self.assertEqual(TERMINAL_NODE, "reports")
        self.assertEqual(STEP_SEQUENCE[-1][0], "reports")

    def test_base_dir_is_per_recording_under_work_dir(self):
        cfg = _cfg()
        expected = Path(cfg.work_dir) / "nipype" / "sub-S001" / "ses-V1"
        self.assertEqual(recording_base_dir(cfg, "S001", "V1"), expected)
        self.assertEqual(recording_base_dir(cfg, "S001", None).name, "ses-none")

    def test_node_input_hash_is_deterministic_and_config_sensitive(self):
        wf = build_recording_workflow(_cfg(), "S001", "V1")
        prepare = next(n for n in wf._graph.nodes() if n.name == "prepare")
        h1 = prepare.inputs.get_hashval()[1]
        self.assertEqual(h1, prepare.inputs.get_hashval()[1])
        wf2 = build_recording_workflow(_cfg(spike_percentile=95.0), "S001", "V1")
        prepare2 = next(n for n in wf2._graph.nodes() if n.name == "prepare")
        self.assertNotEqual(h1, prepare2.inputs.get_hashval()[1])

    def test_node_functions_are_self_contained_for_function_source_serialization(self):
        """Function nodes serialize by source; bodies must not reference module-level names."""
        import inspect

        for name, fn in STEP_SEQUENCE:
            fdef = ast.parse(inspect.getsource(fn)).body[0]
            params = {a.arg for a in fdef.args.args}
            assigned, imported, used = set(), set(), set()
            for node in ast.walk(fdef):
                if isinstance(node, ast.Name):
                    (assigned if isinstance(node.ctx, ast.Store) else used).add(node.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        imported.add((a.asname or a.name).split(".")[0])
            free = used - params - assigned - imported - set(dir(builtins))
            self.assertEqual(free, set(), f"{name} references non-self-contained names: {sorted(free)}")


class StepInterfaceHashTests(unittest.TestCase):
    """The node cache key must be deterministic across processes: hash on
    (step, config, subject, session), never on the fat ctx (which can hold
    address-bearing objects like a nibabel template image)."""

    def _iface(self, cfg, step="tissue_probmaps", ctx=None):
        from mrsiprep.workflows.nipype_engine.adapters import StepInterface

        it = StepInterface()
        it.inputs.step = step
        it.inputs.config = cfg
        it.inputs.subject = "S001"
        it.inputs.session = "V1"
        it.inputs.ctx = {} if ctx is None else ctx
        return it

    def test_ctx_does_not_affect_hash(self):
        cfg = _cfg()
        base = self._iface(cfg, ctx={}).inputs.get_hashval()[1]
        # An object() has an address-bearing repr; must not change the hash.
        with_obj = self._iface(cfg, ctx={"registration": object(), "x": [1, 2]}).inputs.get_hashval()[1]
        self.assertEqual(base, with_obj)

    def test_config_and_step_affect_hash(self):
        base = self._iface(_cfg()).inputs.get_hashval()[1]
        self.assertNotEqual(base, self._iface(_cfg(spike_percentile=95.0)).inputs.get_hashval()[1])
        self.assertNotEqual(base, self._iface(_cfg(), step="pvc").inputs.get_hashval()[1])


class NipypeEngineDispatchTests(unittest.TestCase):
    def test_serial_runs_one_call_per_ready_recording(self):
        import mrsiprep.workflows.nipype_engine.run as run_mod

        calls = []

        def fake_run_one(config, subject, session, subject_template=None):
            calls.append((subject, session))
            return f"{subject}/{session}"

        original = run_mod._run_one_recording_nipype
        run_mod._run_one_recording_nipype = fake_run_one
        try:
            cfg = _cfg(nproc=1)
            ready = [
                type("R", (), {"subject": "S001", "session": "V1"})(),
                type("R", (), {"subject": "S002", "session": None})(),
            ]
            out = run_mod.execute_recordings_nipype(cfg, ready)
        finally:
            run_mod._run_one_recording_nipype = original
        self.assertEqual(calls, [("S001", "V1"), ("S002", None)])
        self.assertEqual(out, ["S001/V1", "S002/None"])

    def test_runtime_failure_is_isolated_per_recording(self):
        """A recording that raises mid-run yields status='failed' without
        propagating, so the batch continues (batch-safety)."""
        import mrsiprep.workflows.nipype_engine.build as build_mod
        import mrsiprep.workflows.nipype_engine.run as run_mod

        def boom(config, subject, session, subject_template=None):
            raise RuntimeError("synthetic step failure")

        original = build_mod.build_recording_workflow
        build_mod.build_recording_workflow = boom
        try:
            status = run_mod._run_one_recording_nipype(_cfg(), "S001", "V1")
        finally:
            build_mod.build_recording_workflow = original
        self.assertEqual(status.status, "failed")
        self.assertIn("synthetic step failure", status.error)
        self.assertEqual((status.subject, status.session), ("S001", "V1"))


if __name__ == "__main__":
    unittest.main()
