"""Parcellation workflow."""

from __future__ import annotations

from mrsiprep.parcellation.chimera_native import run_chimera_parcellation
from mrsiprep.parcellation.mni_atlas import run_mni_parcellation
from mrsiprep.parcellation.synthseg import run_synthseg_parcellation


def run_parcellation_workflow(config, subject, session, mrsi_reference, registration_result, raw_t1=None, t1_reference=None):
    """Dispatch to the configured parcellation backend and project atlas labels into MRSI-native space.

    Backend is selected via ``config.parcellation_mode``:

    - ``"synthseg"`` -- SynthSeg cortical/subcortical labels, projected
      via the inverse MRSI→T1w transform (``registration_result.mrsi_to_t1.inverse``).
      Requires ``raw_t1``.
    - ``"chimera"`` -- Chimera multi-atlas fusion, same inverse-transform
      projection.
    - ``"atlas"`` -- a bundled or custom standardized MNI-space atlas,
      projected via both the inverse T1w→MNI and inverse MRSI→T1w
      transforms. Requires ``registration_result.t1_to_mni`` to be set
      (i.e. MNI normalization ran) and a ``t1_reference`` image.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param mrsi_reference: Reference-metabolite image defining the target MRSI grid.
    :param registration_result: :class:`mrsiprep.workflows.registration.RegistrationResult`
        for this recording, supplying the inverse transforms used to
        project atlas labels into MRSI space.
    :param raw_t1: Non-skull-stripped T1w, required for ``"synthseg"``.
    :param t1_reference: T1w-space reference image, required for ``"atlas"``.
    :returns: Backend-specific parcellation result object (see
        :mod:`mrsiprep.parcellation.synthseg`,
        :mod:`mrsiprep.parcellation.chimera_native`, or
        :mod:`mrsiprep.parcellation.mni_atlas`).
    :raises FileNotFoundError: If ``"synthseg"`` is selected without ``raw_t1``.
    :raises RuntimeError: If ``"atlas"`` is selected but T1w-to-MNI
        normalization wasn't run.
    :raises ValueError: If ``"atlas"`` is selected without ``t1_reference``,
        or ``config.parcellation_mode`` isn't a supported value.
    """
    if config.parcellation_mode == "synthseg":
        if raw_t1 is None:
            raise FileNotFoundError("SynthSeg parcellation requires a raw T1w image.")
        return run_synthseg_parcellation(
            config,
            subject,
            session,
            raw_t1,
            mrsi_reference,
            registration_result.mrsi_to_t1.inverse,
        )
    if config.parcellation_mode == "chimera":
        return run_chimera_parcellation(config, subject, session, mrsi_reference, registration_result.mrsi_to_t1.inverse)
    if config.parcellation_mode == "atlas":
        if registration_result.t1_to_mni is None:
            raise RuntimeError("Atlas parcellation requires T1-to-MNI normalization.")
        if t1_reference is None:
            raise ValueError("Atlas parcellation requires a T1 reference image.")
        return run_mni_parcellation(
            config,
            subject,
            session,
            mrsi_reference,
            t1_reference,
            registration_result.t1_to_mni.inverse,
            registration_result.mrsi_to_t1.inverse,
        )
    raise ValueError(f"Unsupported parcellation mode: {config.parcellation_mode}")
