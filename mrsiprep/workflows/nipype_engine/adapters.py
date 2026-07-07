"""Custom Nipype interface wrapping an MRSIPrep step function.

Why a custom interface instead of ``niu.Function``: the step results threaded
through ``ctx`` include objects with non-deterministic ``repr`` (e.g.
``T1ToMNIResult.template`` is a nibabel image whose default repr embeds a memory
address). Hashing ``ctx`` would therefore vary across processes and defeat
caching on every rerun.

Each node's output is fully determined by ``(config, subject, session)`` for a
fixed input dataset --- and ``config`` carries every processing parameter plus
the ``overwrite_*`` flags. So we hash only those (deterministic) inputs and flow
``ctx`` as data with ``nohash=True``. This yields coarse-but-correct caching
aligned with the step functions' own ``overwrite`` + ``out.exists()`` guards:
rerunning a completed recording skips the cached nodes; changing any processing parameter
(hence ``config``) or passing ``--overwrite`` recomputes. (Content-level
invalidation on individual input files remains a future refinement.)
"""

from __future__ import annotations

from nipype.interfaces.base import BaseInterface, BaseInterfaceInputSpec, TraitedSpec, traits

from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE

STEP_FUNCS = dict(STEP_SEQUENCE)


class StepInputSpec(BaseInterfaceInputSpec):
    step = traits.Str(mandatory=True)
    config = traits.Any(mandatory=True)
    subject = traits.Str(mandatory=True)
    session = traits.Any()
    # Threaded data only; excluded from the node hash (see module docstring).
    ctx = traits.Any(nohash=True)


class StepOutputSpec(TraitedSpec):
    ctx = traits.Any()


class StepInterface(BaseInterface):
    input_spec = StepInputSpec
    output_spec = StepOutputSpec

    def _run_interface(self, runtime):
        func = STEP_FUNCS[self.inputs.step]
        ctx_in = self.inputs.ctx if isinstance(self.inputs.ctx, dict) else {}
        self._ctx = func(self.inputs.config, self.inputs.subject, self.inputs.session, ctx_in)
        return runtime

    def _list_outputs(self):
        return {"ctx": self._ctx}
