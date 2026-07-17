"""Build a per-recording Nipype workflow from the step sequence.

The DAG is a linear chain that threads a single ``ctx`` dict through cached
Function nodes (see :mod:`mrsiprep.workflows.nipype_engine.nodes`). Because the
MRSI pipeline is an inherent data-dependency chain, a linear graph captures its
true structure; the payoff is Nipype's per-node content/value hashing, which
skips unchanged steps on rerun. Each node writes its derivatives straight to the
BIDS layout as before; ``base_dir`` holds only the node result caches.
"""

from __future__ import annotations

from pathlib import Path

from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE

TERMINAL_NODE = STEP_SEQUENCE[-1][0]


def recording_base_dir(config, subject: str, session: str | None) -> Path:
    ses = f"ses-{session}" if session else "ses-none"
    return Path(config.work_dir) / "nipype" / f"sub-{subject}" / ses


def build_recording_workflow(config, subject: str, session: str | None, subject_template=None):
    """Return a linear ``pe.Workflow`` for one recording.

    The returned workflow's terminal node (:data:`TERMINAL_NODE`) exposes the
    final ``ctx`` on its ``ctx`` output; ``ctx['outputs']`` is the outputs dict.

    Each node wraps a step function via :class:`StepInterface`, which hashes only
    ``(step, config, subject, session)`` --- deterministic across processes --- and
    flows ``ctx`` unhashed, so completed recordings hit the node cache on rerun.

    ``subject_template`` is an optional precomputed ``SubjectTemplateResult``
    (see ``mrsiprep.registration.subject_template``), seeded into the initial
    ``ctx`` so ``step_registration`` can compose (session->template)+
    (template->MNI) instead of registering this session directly to MNI.

    The live-status-table queue (see ``nipype_engine.run``) is deliberately
    NOT threaded through ``ctx`` -- Nipype deep-copies every node's ``ctx``
    input between steps, and deep-copying a multiprocessing.Manager Queue
    proxy tries to RPC back to the manager process and fails
    (``TypeError: cannot pickle '_thread.lock' object``). It's set as a
    process-local global instead (``mrsiprep.utils.debug.set_status_queue``),
    the same pattern already used for the per-recording logbook.
    """
    import nipype.pipeline.engine as pe

    from mrsiprep.workflows.nipype_engine.adapters import StepInterface

    base_dir = recording_base_dir(config, subject, session)
    base_dir.mkdir(parents=True, exist_ok=True)

    wf = pe.Workflow(name="mrsiprep_recording", base_dir=str(base_dir))

    nodes = []
    for name, _func in STEP_SEQUENCE:
        node = pe.Node(StepInterface(), name=name)
        node.inputs.step = name
        node.inputs.config = config
        node.inputs.subject = subject
        node.inputs.session = session
        nodes.append(node)

    # Seed the first node with the initial context; thread ctx through the chain.
    nodes[0].inputs.ctx = {"subject_template": subject_template}
    for prev, nxt in zip(nodes, nodes[1:]):
        wf.connect(prev, "ctx", nxt, "ctx")

    # A single-node workflow still needs its node registered.
    if len(nodes) == 1:
        wf.add_nodes(nodes)

    return wf
