"""Registration workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.registration.mrsi_to_t1 import MRSIToT1Result, run_mrsi_to_t1
from mrsiprep.registration.t1_to_mni import T1ToMNIResult, run_t1_to_mni


@dataclass
class RegistrationResult:
    mrsi_to_t1: MRSIToT1Result
    t1_to_mni: T1ToMNIResult | None


def run_registration_workflow(config, subject: str, session: str | None, mrsi_reference: Path, registration_t1: Path, registration_mask: Path | None = None) -> RegistrationResult:
    mrsi_to_t1 = run_mrsi_to_t1(config, subject, session, mrsi_reference, registration_t1, fixed_mask=registration_mask)
    t1_to_mni = None
    if "MNI152NLin2009cAsym" in config.output_spaces or config.parcellation_mode == "mni" or "mni" in config.transform:
        t1_to_mni = run_t1_to_mni(config, subject, session, registration_t1, mrsi_reference=mrsi_reference)
    return RegistrationResult(mrsi_to_t1=mrsi_to_t1, t1_to_mni=t1_to_mni)
