"""Declared per-step data dependencies, backing ``--steps``.

:data:`STEP_SEQUENCE` (see :mod:`nodes`) threads a shared ``ctx`` dict through
a fixed 19-step chain; each step reads some ``ctx`` keys and writes others,
but that dependency structure only exists implicitly, inside each step
function's body (``ctx["key"]`` vs ``ctx.get("key")``). :data:`STEP_DEPENDENCIES`
makes it explicit, so a user-supplied custom order/subset (``--steps``) can be
validated before a run starts rather than failing with a bare ``KeyError``
partway through.

Built and checked by hand against ``nodes.py``/``steps.py`` directly (not
inferred from call signatures: several node wrappers, e.g. ``step_prepare``,
``step_tissue_qc``, ``step_reports``, don't correspond 1:1 to one
``_step_*`` call, and the required-vs-optional split only exists as
``ctx[...]`` vs ``ctx.get(...)`` inside each wrapper body).

``registration``'s ``subject_template`` optional dependency is
seeded once into the initial ``ctx`` (see ``build.py``/``participant.py``),
not produced by any step -- it is deliberately absent from every step's
``produces`` and therefore never reported as a producible/missing key.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDeps:
    requires: frozenset[str]
    produces: frozenset[str]
    optional: frozenset[str] = frozenset()


STEP_DEPENDENCIES: dict[str, StepDeps] = {
    "prepare": StepDeps(
        requires=frozenset(),
        produces=frozenset({"t1_path", "inputs", "raw_t1"}),
    ),
    "tissue_seg": StepDeps(
        requires=frozenset({"raw_t1", "t1_path"}),
        produces=frozenset({"t1_path", "precomputed_tissue_t1", "p3_override", "brain_mask_override"}),
    ),
    "anatprep": StepDeps(
        requires=frozenset({"t1_path", "p3_override", "brain_mask_override"}),
        produces=frozenset({"anatprep"}),
    ),
    "mrsi_load": StepDeps(
        requires=frozenset({"inputs"}),
        optional=frozenset({"anatprep"}),
        produces=frozenset({"mrsi_load"}),
    ),
    "spike_filter": StepDeps(
        requires=frozenset({"mrsi_load"}),
        produces=frozenset({"spike_filter", "qc_sections_mrsi_raw", "qc_sections_mrsi_preproc"}),
    ),
    "t1_saturation_correction": StepDeps(
        requires=frozenset({"mrsi_load", "spike_filter"}),
        produces=frozenset({"t1_saturation_correction", "qc_sections_t1_correction"}),
    ),
    "mrsi_reference": StepDeps(
        requires=frozenset({"mrsi_load", "spike_filter", "t1_saturation_correction", "inputs"}),
        produces=frozenset({"mrsi_reference"}),
    ),
    "mrsi_quality": StepDeps(
        requires=frozenset({"t1_saturation_correction", "inputs", "mrsi_reference"}),
        produces=frozenset({"mrsi_quality"}),
    ),
    "registration": StepDeps(
        requires=frozenset({"mrsi_reference", "anatprep"}),
        optional=frozenset({"subject_template"}),
        produces=frozenset({"registration"}),
    ),
    "tissue_probmaps": StepDeps(
        requires=frozenset({"anatprep", "mrsi_reference", "registration", "precomputed_tissue_t1"}),
        produces=frozenset({"tissue"}),
    ),
    "tissue_qc": StepDeps(
        requires=frozenset({"tissue", "raw_t1"}),
        produces=frozenset({"qc_sections_tissue"}),
    ),
    "pvc": StepDeps(
        requires=frozenset({"mrsi_reference", "tissue"}),
        produces=frozenset({"corrected_maps", "tissue_4d", "qc_sections_mrsi_pvc"}),
    ),
    "resampling": StepDeps(
        requires=frozenset({"anatprep", "mrsi_reference", "registration", "corrected_maps", "raw_t1"}),
        produces=frozenset({
            "transformed", "qc_sections_t1w_alignment", "qc_sections_mni_alignment",
            "qc_sections_mrsi_t1w", "qc_sections_mrsi_template",
        }),
    ),
    "leakage_qc": StepDeps(
        requires=frozenset({"anatprep", "transformed"}),
        produces=frozenset({"leakage_qc"}),
    ),
    "anat_parcellation_qc": StepDeps(
        requires=frozenset({"raw_t1", "mrsi_reference", "mrsi_quality", "registration"}),
        optional=frozenset({"transformed"}),
        produces=frozenset({"preliminary_parcels", "parcel_qc"}),
    ),
    "mrsi_parcellation": StepDeps(
        requires=frozenset({"raw_t1", "mrsi_reference", "anatprep", "registration", "preliminary_parcels"}),
        produces=frozenset({"parcels", "qc_sections_parcellation"}),
    ),
    "regional": StepDeps(
        requires=frozenset({"corrected_maps", "parcels", "mrsi_reference", "mrsi_quality", "tissue"}),
        produces=frozenset({"regional"}),
    ),
    "connectivity": StepDeps(
        requires=frozenset({"regional", "parcels", "corrected_maps", "mrsi_reference", "tissue"}),
        produces=frozenset({"connectivity", "qc_sections_connectivity"}),
    ),
    "metprofiles": StepDeps(
        requires=frozenset({"corrected_maps", "mrsi_reference", "parcels", "regional", "anatprep"}),
        produces=frozenset({"metprofiles"}),
    ),
    "reports": StepDeps(
        requires=frozenset({
            "anatprep", "mrsi_reference", "mrsi_quality", "parcels", "parcel_qc", "leakage_qc", "tissue_4d",
            "preliminary_parcels", "regional", "metprofiles", "connectivity", "transformed", "registration",
            "raw_t1", "qc_sections_tissue", "qc_sections_mrsi_raw", "qc_sections_mrsi_preproc",
            "qc_sections_t1_correction", "qc_sections_t1w_alignment", "qc_sections_mni_alignment",
            "qc_sections_parcellation", "qc_sections_connectivity",
        }),
        optional=frozenset({"qc_sections_mrsi_pvc", "qc_sections_mrsi_t1w", "qc_sections_mrsi_template"}),
        produces=frozenset({"outputs"}),
    ),
}


def _producers_of(key: str) -> list[str]:
    return sorted(name for name, deps in STEP_DEPENDENCIES.items() if key in deps.produces)


def validate_step_order(names: list[str]) -> None:
    """Hard-fail if ``names`` (a ``--steps`` request) violates a declared
    dependency -- a step listed before whatever produces a key it requires.

    Unknown step names, and any step used before its producer(s) appear
    earlier in the list, each raise :class:`ValueError` naming exactly what
    is wrong and (for a missing dependency) which step(s) would supply it.
    Optional dependencies never block: a step missing only an optional key
    still runs, just without that behavior (mirrors the real step bodies,
    which read optional keys via ``ctx.get(...)``).
    """
    unknown = sorted(set(names) - STEP_DEPENDENCIES.keys())
    if unknown:
        raise ValueError(f"--steps: unknown step(s) {unknown}. Valid steps: {sorted(STEP_DEPENDENCIES)}.")

    available: set[str] = set()
    for name in names:
        deps = STEP_DEPENDENCIES[name]
        missing = deps.requires - available
        if missing:
            producers = {key: _producers_of(key) for key in sorted(missing)}
            raise ValueError(
                f"--steps: step '{name}' requires {sorted(missing)}, which no earlier step in --steps "
                f"produces. Insert the step(s) that produce each one earlier in --steps: {producers}."
            )
        available |= deps.produces


def resolve_step_order(config) -> list[tuple[str, object]]:
    """The ``(name, callable)`` pairs to run, in order, for ``config``.

    Returns :data:`nodes.STEP_SEQUENCE` unchanged (the full default order)
    when ``config.steps`` is ``None`` -- the ``--steps``-omitted case, which
    must behave identically to today's fixed pipeline. Otherwise looks up
    each requested name against the live ``STEP_SEQUENCE`` registry (not a
    copy taken at import time, so tests patching it still apply) and returns
    that reordered/subset pair-list. Does not re-validate: validation runs
    once, at config construction (``MRSIPrepConfig.__post_init__``).
    """
    from mrsiprep.workflows.nipype_engine.nodes import STEP_SEQUENCE

    if config.steps is None:
        return STEP_SEQUENCE
    by_name = dict(STEP_SEQUENCE)
    return [(name, by_name[name]) for name in config.steps]


def terminal_node(config) -> str:
    """Name of the last step that will run for ``config``."""
    return resolve_step_order(config)[-1][0]
