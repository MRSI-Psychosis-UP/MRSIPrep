"""Node bodies for the Nipype engine --- the canonical per-recording pipeline.

Each function has the uniform signature ``(config, subject, session, ctx) -> ctx``
and runs one stage of the recording pipeline by calling the shared ``_step_*``
functions in :mod:`mrsiprep.workflows.participant`, threading a context dict
between stages. Together they reproduce the full sequence (both ``mni-norm`` and
``parc-con`` modes; each ``_step_*`` gates its own mode internally).

These bodies are kept self-contained (imports live inside each function, and
each builds its own tagged ``Debug`` inline rather than calling a shared
module-level helper) so they also survive Nipype's ``Function`` source
serialization if ever wrapped that way; the shipped nodes use
:class:`~mrsiprep.workflows.nipype_engine.adapters.StepInterface`. The
``Debug`` tag (``sub-<label>`` / ``sub-<label> ses-<label>``) is what makes
concurrent ``--nproc`` workers' interleaved console output attributable to
the right recording.

``STEP_SEQUENCE`` lists the nodes in execution order; :mod:`build` wires them
into a linear ``ctx``-threading workflow.
"""

from __future__ import annotations


def step_prepare(config, subject, session, ctx):
    """Validate inputs and seed the context."""
    from mrsiprep.io.bids import BIDSLayout
    from mrsiprep.io.validators import validate_recording

    t1_path, inputs = validate_recording(config, subject, session)
    layout = BIDSLayout(config.bids_dir, filters=config.bids_filters)
    raw_t1 = layout.raw_t1(subject, session)
    if raw_t1 is None:
        raise FileNotFoundError(f"Missing raw T1w required for MRSIPrep: sub-{subject} ses-{session}")
    ctx = dict(ctx)
    ctx.update(t1_path=t1_path, inputs=inputs, raw_t1=raw_t1)
    return ctx


def step_tissue_seg(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_tissue_segmentation

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    t1_path, precomputed_tissue_t1, p3_override, brain_mask_override = _step_tissue_segmentation(
        config, subject, session, ctx["raw_t1"], ctx["t1_path"], debug
    )
    ctx = dict(ctx)
    ctx.update(
        t1_path=t1_path,
        precomputed_tissue_t1=precomputed_tissue_t1,
        p3_override=p3_override,
        brain_mask_override=brain_mask_override,
    )
    return ctx


def step_anat(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_anatomical_prep

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    ctx = dict(ctx)
    ctx["anat"] = _step_anatomical_prep(config, subject, session, ctx["t1_path"], ctx["p3_override"], ctx["brain_mask_override"], debug)
    return ctx


def step_mrsi(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_mrsi_preprocessing

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    mrsi, qc_report_mrsi_preproc = _step_mrsi_preprocessing(config, subject, session, ctx["inputs"], debug)
    ctx = dict(ctx)
    ctx.update(mrsi=mrsi, qc_report_mrsi_preproc=qc_report_mrsi_preproc)
    return ctx


def step_registration(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_registration

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    ctx = dict(ctx)
    ctx["registration"] = _step_registration(
        config, subject, session, ctx["mrsi"], ctx["anat"], debug, subject_template=ctx.get("subject_template")
    )
    return ctx


def step_tissue_probmaps(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_tissue_probmaps

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    ctx = dict(ctx)
    ctx["tissue"] = _step_tissue_probmaps(
        config, subject, session, ctx["anat"], ctx["mrsi"], ctx["registration"], ctx["precomputed_tissue_t1"], debug
    )
    return ctx


def step_tissue_qc(config, subject, session, ctx):
    """Tissue QC report."""
    from mrsiprep.reports.tissue import write_tissue_qc_report
    from mrsiprep.tissue.synthseg_fast import synthseg_native_labels_path

    # synthseg-fast is now also mni-norm's tissue backend (not just
    # parc-con's), so gate on the label file actually existing rather than
    # on a stale (mode, backend) pair that predates that change.
    candidate_dseg = synthseg_native_labels_path(config, subject, session)
    dseg_for_qc = candidate_dseg if candidate_dseg.exists() else None
    tissue = ctx["tissue"]
    ctx = dict(ctx)
    ctx["qc_report_tissue"] = write_tissue_qc_report(
        config, subject, session, ctx["raw_t1"], dseg_for_qc, tissue.t1 if tissue is not None else None
    )
    return ctx


def step_pvc(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_pvc

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    corrected_maps, tissue_4d = _step_pvc(config, subject, session, ctx["mrsi"], ctx["tissue"], debug)
    ctx = dict(ctx)
    ctx.update(corrected_maps=corrected_maps, tissue_4d=tissue_4d)
    return ctx


def step_resampling(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_resampling

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    transformed, qc_report_registration = _step_resampling(
        config, subject, session, ctx["anat"], ctx["mrsi"], ctx["registration"], ctx["corrected_maps"], ctx["raw_t1"], debug
    )
    ctx = dict(ctx)
    ctx.update(transformed=transformed, qc_report_registration=qc_report_registration)
    return ctx


def step_synthseg_parc_qc(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_synthseg_parcellation_qc

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    preliminary_parcels, parcel_qc = _step_synthseg_parcellation_qc(config, subject, session, ctx["raw_t1"], ctx["mrsi"], ctx["registration"], debug)
    ctx = dict(ctx)
    ctx.update(preliminary_parcels=preliminary_parcels, parcel_qc=parcel_qc)
    return ctx


def step_parcellation(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_parcellation

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    parcels, qc_report_parcellation = _step_parcellation(
        config, subject, session, ctx["raw_t1"], ctx["mrsi"], ctx["anat"], ctx["registration"], ctx["preliminary_parcels"], debug
    )
    ctx = dict(ctx)
    ctx.update(parcels=parcels, qc_report_parcellation=qc_report_parcellation)
    return ctx


def step_regional(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_regional_extraction

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    regional, regional_regression = _step_regional_extraction(
        config, subject, session, ctx["corrected_maps"], ctx["parcels"], ctx["mrsi"], ctx["tissue"], debug
    )
    ctx = dict(ctx)
    ctx.update(regional=regional, regional_regression=regional_regression)
    return ctx


def step_connectivity(config, subject, session, ctx):
    from mrsiprep.utils.debug import Debug
    from mrsiprep.workflows.participant import _step_connectivity

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    connectivity, qc_report_connectivity = _step_connectivity(
        config, subject, session, ctx["regional"], ctx["parcels"], ctx["corrected_maps"], ctx["mrsi"], ctx["tissue"], debug
    )
    ctx = dict(ctx)
    ctx.update(connectivity=connectivity, qc_report_connectivity=qc_report_connectivity)
    return ctx


def step_metprofiles(config, subject, session, ctx):
    from mrsiprep.workflows.participant import _step_metprofiles

    ctx = dict(ctx)
    ctx["metprofiles"] = _step_metprofiles(
        config, subject, session, ctx["corrected_maps"], ctx["mrsi"], ctx["parcels"], ctx["regional"], ctx["anat"]
    )
    return ctx


def step_reports(config, subject, session, ctx):
    """Assemble outputs, run reports, write provenance."""
    from mrsiprep.io.naming import provenance_derivative
    from mrsiprep.utils.debug import Debug
    from mrsiprep.utils.provenance import write_provenance
    from mrsiprep.workflows.participant import _step_reports

    debug = Debug(verbose=config.verbose, tag=f"sub-{subject}" + (f" ses-{session}" if session else ""))
    anat = ctx["anat"]
    mrsi = ctx["mrsi"]
    parcels = ctx["parcels"]
    outputs = {
        "t1w": anat.t1w,
        "registration_t1w": anat.registration_t1w,
        "mrsi_reference": mrsi.reference,
        "qc_summary": mrsi.qc_summary,
        "parcel_qc": ctx["parcel_qc"],
        "tissue_4d": ctx["tissue_4d"],
        "atlas_mrsi": parcels.atlas_mrsi,
        "preliminary_atlas_mrsi": ctx["preliminary_parcels"].atlas_mrsi,
        "regional_table": ctx["regional"],
        "regional_tissue_regression": ctx.get("regional_regression"),
        "metprofiles": ctx["metprofiles"],
        "connectivity": ctx["connectivity"],
        "transformed_maps": ctx["transformed"],
        "qc_report_tissue": ctx["qc_report_tissue"],
        "qc_report_mrsi_preproc": ctx["qc_report_mrsi_preproc"],
        "qc_report_registration": ctx["qc_report_registration"],
        "qc_report_parcellation": ctx["qc_report_parcellation"],
        "qc_report_connectivity": ctx["qc_report_connectivity"],
    }
    outputs = _step_reports(config, subject, session, outputs, debug)
    outputs["provenance"] = write_provenance(
        config,
        provenance_derivative(config.derivative_dir, subject, session),
        {"subject": subject, "session": session, "outputs": outputs},
    )
    ctx = dict(ctx)
    ctx["outputs"] = outputs
    return ctx


# Execution order (node name, callable).
STEP_SEQUENCE = [
    ("prepare", step_prepare),
    ("tissue_seg", step_tissue_seg),
    ("anat", step_anat),
    ("mrsi", step_mrsi),
    ("registration", step_registration),
    ("tissue_probmaps", step_tissue_probmaps),
    ("tissue_qc", step_tissue_qc),
    ("pvc", step_pvc),
    ("resampling", step_resampling),
    ("synthseg_parc_qc", step_synthseg_parc_qc),
    ("parcellation", step_parcellation),
    ("regional", step_regional),
    ("connectivity", step_connectivity),
    ("metprofiles", step_metprofiles),
    ("reports", step_reports),
]
