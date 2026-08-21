"""Registration workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.registration.mrsi_to_t1 import MRSIToT1Result, run_mrsi_to_t1
from mrsiprep.registration.t1_to_mni import T1ToMNIResult, compose_longitudinal_t1_to_mni, run_t1_to_mni


@dataclass
class RegistrationResult:
    """Forward/inverse transforms produced by :func:`run_registration_workflow`."""

    mrsi_to_t1: MRSIToT1Result
    t1_to_mni: T1ToMNIResult | None


def run_registration_workflow(
    config,
    subject: str,
    session: str | None,
    mrsi_reference: Path,
    registration_t1: Path,
    registration_mask: Path | None = None,
    mrsi_mask: Path | None = None,
    subject_template=None,
) -> RegistrationResult:
    """Register one recording's MRSI reference to T1w, and T1w to MNI if requested.

    MRSI→T1w always runs, via :func:`mrsiprep.registration.mrsi_to_t1.run_mrsi_to_t1`.
    T1w→MNI only runs when MNI output space, MNI parcellation, or an MNI
    transform is actually requested by ``config``.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param mrsi_reference: Reference-metabolite image driving MRSI→T1w registration.
    :param registration_t1: T1w image to register to (see
        :func:`mrsiprep.workflows.anatomical.prepare_anatomical`'s
        ``registration_t1w``).
    :param registration_mask: T1w-side fixed mask for registration, if any.
    :param mrsi_mask: MRSI-native brainmask; only used by the ``fsl``
        backend's FNIRT stage, as the moving-side mask FNIRT needs
        alongside ``registration_mask``.
    :param subject_template: Optional precomputed
        :class:`~mrsiprep.registration.subject_template.SubjectTemplateResult`,
        built once per subject when ``--longitudinal`` is on and the
        subject has 2+ sessions. When present, T1w-to-MNI is composed via
        (session→template)+(template→MNI) instead of registering this
        session directly to MNI.
    :returns: :class:`RegistrationResult` with the MRSI→T1w transforms
        always set, and T1w→MNI transforms set only when that stage ran.
    """
    mrsi_to_t1 = run_mrsi_to_t1(config, subject, session, mrsi_reference, registration_t1, fixed_mask=registration_mask, moving_mask=mrsi_mask)
    t1_to_mni = None
    if "MNI152NLin2009cAsym" in config.output_spaces or config.parcellation_mode == "mni" or "mni" in config.transform:
        if subject_template is not None and session is not None:
            t1_to_mni = compose_longitudinal_t1_to_mni(config, subject, session, subject_template, registration_t1, mrsi_reference=mrsi_reference)
        else:
            t1_to_mni = run_t1_to_mni(config, subject, session, registration_t1, mrsi_reference=mrsi_reference)
    return RegistrationResult(mrsi_to_t1=mrsi_to_t1, t1_to_mni=t1_to_mni)
