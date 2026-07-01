"""MRSI preprocessing workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.mrsi.filtering import filter_metabolite_maps
from mrsiprep.mrsi.masks import ensure_brainmask
from mrsiprep.mrsi.quality import make_quality_masks
from mrsiprep.mrsi.reference import generate_reference


@dataclass
class MRSIResult:
    raw_maps: dict[str, Path]
    preproc_maps: dict[str, Path]
    corrected_maps: dict[str, Path]
    crlb_maps: dict[str, Path]
    snr_map: Path | None
    linewidth_map: Path | None
    water_map: Path | None
    brainmask: Path
    reference: Path
    qcmasks: dict[str, Path]
    qc_summary: Path


def _symlink_quality_maps(config, subject: str, session: str | None, inputs: MRSIInputs) -> None:
    links: list[tuple[Path | None, dict]] = [(inputs.snr_map, {"desc": "snr"}), (inputs.linewidth_map, {"desc": "fwhm"})]
    for met, path in inputs.crlb_maps.items():
        links.append((path, {"met": met, "desc": "crlb"}))
    for source, entities in links:
        if source is None or not source.exists():
            continue
        target = mrsi_derivative(config.derivative_dir, subject, session, space="orig", suffix_override="mrsi", **entities)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(source.resolve())


def run_mrsi_workflow(config, subject: str, session: str | None, inputs: MRSIInputs) -> MRSIResult:
    _symlink_quality_maps(config, subject, session, inputs)
    brainmask = ensure_brainmask(config, subject, session, inputs.brainmask, inputs.water_map, inputs.metabolite_maps)
    preproc = inputs.metabolite_maps
    if config.processing_mode == "parc-con":
        preproc = filter_metabolite_maps(config, subject, session, inputs.metabolite_maps, brainmask)
    reference = generate_reference(config, subject, session, preproc, preferred_met=config.ref_met)
    qcmasks, qc_summary = make_quality_masks(
        config,
        subject,
        session,
        preproc,
        inputs.crlb_maps,
        inputs.snr_map,
        inputs.linewidth_map,
        brainmask,
    )
    return MRSIResult(
        raw_maps=inputs.metabolite_maps,
        preproc_maps=preproc,
        corrected_maps=preproc,
        crlb_maps=inputs.crlb_maps,
        snr_map=inputs.snr_map,
        linewidth_map=inputs.linewidth_map,
        water_map=inputs.water_map,
        brainmask=brainmask,
        reference=reference,
        qcmasks=qcmasks,
        qc_summary=qc_summary,
    )
