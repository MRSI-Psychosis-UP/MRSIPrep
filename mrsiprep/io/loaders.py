"""MRSI input loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mrsiprep.io.bids import BIDSLayout


@dataclass
class MRSIInputs:
    metabolite_maps: dict[str, Path] = field(default_factory=dict)
    crlb_maps: dict[str, Path] = field(default_factory=dict)
    snr_map: Path | None = None
    linewidth_map: Path | None = None
    brainmask: Path | None = None
    water_map: Path | None = None


def load_mrsi_inputs(layout: BIDSLayout, subject: str, session: str | None, metabolites: list[str]) -> MRSIInputs:
    out = MRSIInputs()
    for met in metabolites:
        signal = layout.mrsi_map(subject, session, "signal", met=met, space="orig")
        if signal:
            out.metabolite_maps[met] = signal
        crlb = layout.mrsi_map(subject, session, "crlb", met=met, space="orig")
        if crlb:
            out.crlb_maps[met] = crlb
    out.snr_map = layout.mrsi_map(subject, session, "snr", space="orig")
    out.linewidth_map = layout.mrsi_map(subject, session, "fwhm", space="orig") or layout.mrsi_map(subject, session, "linewidth", space="orig")
    out.brainmask = layout.mrsi_map(subject, session, "brainmask", space="orig")
    out.water_map = layout.mrsi_map(subject, session, "signal", met="water", space="orig")
    return out
