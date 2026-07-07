"""Parcellation workflow."""

from __future__ import annotations

from mrsiprep.parcellation.chimera_native import run_chimera_parcellation
from mrsiprep.parcellation.mni_atlas import run_mni_parcellation
from mrsiprep.parcellation.synthseg import run_synthseg_parcellation


def run_parcellation_workflow(config, subject, session, mrsi_reference, registration_result, raw_t1=None, t1_reference=None):
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
    if config.parcellation_mode == "mni":
        if registration_result.t1_to_mni is None:
            raise RuntimeError("MNI parcellation requires T1-to-MNI normalization.")
        if t1_reference is None:
            raise ValueError("MNI parcellation requires a T1 reference image.")
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
