"""MRSI preprocessing workflow."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from mrsiprep.io.loaders import MRSIInputs
from mrsiprep.io.mrsinmrs import resolve_mrsinmrs
from mrsiprep.io.naming import mrsi_derivative
from mrsiprep.mrsi.filtering import filter_metabolite_maps
from mrsiprep.mrsi.masks import ensure_brainmask
from mrsiprep.mrsi.orientation import correct_mrsi_orientation
from mrsiprep.mrsi.quality import make_quality_masks
from mrsiprep.mrsi.reference import generate_reference
from mrsiprep.mrsi.t1_correction import apply_t1_correction, apply_t1_correction_voxelwise, resolve_acquisition_params


@dataclass
class MRSIReferenceResult:
    """Native-space MRSI derivatives produced by :func:`run_mrsi_reference_workflow`.

    All paths are in MRSI-native space; per-metabolite maps are keyed by
    metabolite name (e.g. ``"CrPCr"``, matching ``--metabolites``/``--ref-met``).

    :ivar raw_maps: Metabolite signal maps as copied into the derivatives
        tree, unmodified from ``derivatives/mrsi-orig/``.
    :ivar preproc_maps: Metabolite maps after spike detection and
        biharmonic repair (see :func:`mrsiprep.mrsi.filtering.filter_metabolite_maps`).
    :ivar corrected_maps: Identical to ``preproc_maps`` unless
        ``config.t1_correction`` is ``"literature"`` or ``"voxelwise"``, in
        which case this holds the T1-saturation-corrected maps (see
        :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction`/
        :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction_voxelwise`).
        Partial volume correction happens later (see
        :func:`mrsiprep.mrsi.pvc.run_pvc`), not in this workflow, and
        always consumes ``corrected_maps`` as its input.
    :ivar t1_correction_provenance: Per-metabolite T1-correction summary
        rows (TR, T1, source, warnings, plus either a scalar flip
        angle/factor in ``"literature"`` mode or the flip-angle map path
        and a median/non-physical-voxel-fraction summary in
        ``"voxelwise"`` mode), or ``None`` when ``config.t1_correction ==
        "none"``.
    :ivar crlb_maps: Per-metabolite Cramér-Rao lower bound maps, copied
        through unchanged from the raw inputs.
    :ivar snr_map: Whole-brain signal-to-noise-ratio map, if the input
        BIDS layout provided one.
    :ivar linewidth_map: Whole-brain linewidth/FWHM map, if provided.
    :ivar water_map: Water-reference image, if provided (used for coil
        combination / normalization upstream of mrsiprep, not recomputed
        here).
    :ivar flip_angle_map: Measured flip-angle (B1+) map, if provided
        (``desc-b1map``); only consumed when ``config.t1_correction ==
        "voxelwise"``, otherwise carried through unused.
    :ivar brainmask: MRSI-native brainmask, either taken from the inputs
        or derived when missing (see :func:`mrsiprep.mrsi.masks.ensure_brainmask`).
    :ivar reference: The reference-metabolite image used to drive
        MRSI→T1w registration (``config.ref_met``, default ``CrPCr``).
    """

    raw_maps: dict[str, Path]
    preproc_maps: dict[str, Path]
    corrected_maps: dict[str, Path]
    crlb_maps: dict[str, Path]
    snr_map: Path | None
    linewidth_map: Path | None
    water_map: Path | None
    brainmask: Path
    reference: Path
    t1_correction_provenance: list[dict] | None = None
    flip_angle_map: Path | None = None


@dataclass
class MRSIQualityResult:
    """Per-recording voxel-quality derivatives produced by
    :func:`run_mrsi_quality_workflow`.

    :ivar qcmasks: Per-metabolite voxel-quality masks (SNR/CRLB/FWHM
        thresholds applied), keyed the same way as
        :attr:`MRSIReferenceResult.preproc_maps`.
    :ivar qc_summary: Path to the per-recording QC summary table
        produced alongside ``qcmasks``.
    """

    qcmasks: dict[str, Path]
    qc_summary: Path


@dataclass
class MRSILoadResult:
    """Native-space MRSI maps after loading, before spike filtering -- the
    ``mrsi_load`` step's output, consumed by ``spike_filter``.

    :ivar raw_maps: Metabolite signal maps as copied into the derivatives
        tree, unmodified from ``derivatives/mrsi-orig/``.
    :ivar brainmask: MRSI-native brainmask, either taken from the inputs
        or derived when missing (see :func:`mrsiprep.mrsi.masks.ensure_brainmask`).
    :ivar crlb_maps: Per-metabolite Cramér-Rao lower bound maps, copied
        through unchanged from the raw inputs.
    :ivar snr_map: Whole-brain signal-to-noise-ratio map, if provided.
    :ivar linewidth_map: Whole-brain linewidth/FWHM map, if provided.
    :ivar water_map: Water-reference image, if provided.
    :ivar flip_angle_map: Measured flip-angle (B1+) map, if provided
        (``desc-b1map``); only consumed when ``config.t1_correction ==
        "voxelwise"``, otherwise carried through unused.
    """

    raw_maps: dict[str, Path]
    brainmask: Path
    crlb_maps: dict[str, Path]
    snr_map: Path | None
    linewidth_map: Path | None
    water_map: Path | None
    flip_angle_map: Path | None = None


@dataclass
class SpikeFilterResult:
    """Biharmonic spike-filtered metabolite maps -- the ``spike_filter``
    step's output, consumed by ``t1_saturation_correction`` and ``mrsi_reference``.

    :ivar preproc_maps: Metabolite maps after spike detection and
        biharmonic repair (see :func:`mrsiprep.mrsi.filtering.filter_metabolite_maps`),
        or ``load.raw_maps`` itself unchanged when ``config.filter_biharmonic``
        is ``False`` (``--no-filter``).
    """

    preproc_maps: dict[str, Path]


@dataclass
class WaterCorrectionResult:
    """T1-saturation ("water") correction output -- the
    ``t1_saturation_correction`` step's output, consumed by ``mrsi_reference``
    and ``mrsi_quality``.

    When ``config.t1_correction == "none"`` (the default), this is a
    no-op: ``corrected_maps`` is ``load.preproc_maps`` itself (same
    object, not a copy) and ``provenance`` is ``None``.

    :ivar corrected_maps: Identical to the input ``preproc_maps`` unless
        ``config.t1_correction`` is ``"literature"`` or ``"voxelwise"``,
        in which case this holds the T1-saturation-corrected maps (see
        :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction`/
        :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction_voxelwise`).
    :ivar provenance: Per-metabolite T1-correction summary rows, or
        ``None`` when ``config.t1_correction == "none"``.
    """

    corrected_maps: dict[str, Path]
    provenance: list[dict] | None = None


def _same_file(a: Path, b: Path) -> bool:
    """True when `a` and `b` are the same underlying file, even if reached
    through different (e.g. separately bind-mounted) paths."""
    try:
        return a.samefile(b)
    except OSError:
        return False


def _copy_native_maps(config, subject: str, session: str | None, inputs: MRSIInputs) -> None:
    """Copy (not symlink) raw/quality maps into the mrsi/orig derivatives tree.

    A symlink written from inside a container would encode a path relative
    to the container's own mount layout (e.g. separate `/data` and `/out`
    bind mounts), which has no reliable relationship to the host filesystem
    outside the container -- the link would dangle there even though the
    source file exists. Copying these small maps avoids that.
    """
    links: list[tuple[Path | None, dict, str]] = [
        (inputs.snr_map, {"desc": "snr"}, "orig"),
        (inputs.linewidth_map, {"desc": "fwhm"}, "orig"),
        (inputs.water_map, {"met": "water", "desc": "signal"}, "mrsi"),
        (inputs.flip_angle_map, {"desc": "b1map"}, "orig"),
    ]
    for met, path in inputs.crlb_maps.items():
        links.append((path, {"met": met, "desc": "crlb"}, "orig"))
    for met, path in inputs.metabolite_maps.items():
        links.append((path, {"met": met, "desc": "signal"}, "mrsi"))
    for source, entities, space in links:
        if source is None or not source.exists():
            continue
        target = mrsi_derivative(config.derivative_dir, subject, session, space=space, suffix_override="mrsi", **entities)
        if target.exists() and _same_file(source, target):
            # BIDSLayout's mrsi-<space> fallback (see
            # BIDSLayout._mrsi_input_roots) can read raw inputs straight out
            # of mrsiprep's own output tree (mrsi/<space>/) when no separate
            # mrsi-<space> derivatives root exists -- in that case source and
            # target are the same file, and unlinking it before copying would
            # destroy the only copy. Comparing resolved path strings alone is
            # not enough to detect this: the BIDS root and derivatives root
            # are commonly two *separate* Docker bind mounts (e.g. /data and
            # /out) that both happen to point at the same underlying host
            # file, so their in-container resolved paths differ even though
            # they're the same file -- inode identity (samefile) survives
            # that, so it's checked instead/first.
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        try:
            shutil.copy2(source, tmp_target)
        except FileNotFoundError:
            # Source vanished between the exists() check above and the copy
            # (e.g. concurrent regeneration of the input dataset) -- this is
            # an optional/QC-only map, so skip it rather than fail the whole
            # recording.
            tmp_target.unlink(missing_ok=True)
            continue
        except BaseException:
            # Covers KeyboardInterrupt/SIGTERM landing mid-copy too: the
            # partial file is the scratch tmp_target, never the real target,
            # so the existing (or absent) target is left exactly as it was.
            tmp_target.unlink(missing_ok=True)
            raise
        # Atomic on POSIX (same filesystem, since tmp_target sits next to
        # target): either the old target survives untouched or the new one
        # lands complete -- no window where target is missing or truncated,
        # even if a signal arrives right at this line.
        os.replace(tmp_target, target)


def _derivative_map_paths(
    config, subject: str, session: str | None, inputs: MRSIInputs
) -> tuple[dict[str, Path], dict[str, Path], Path | None, Path | None, Path | None, Path | None]:
    """The mrsi/orig/ derivative-tree paths ``_copy_native_maps`` just wrote
    for each of ``inputs``' maps, in the same shape as the input dicts.

    Correcting orientation in place has to target these, not
    ``inputs.metabolite_maps``/etc. directly: those are the *input* BIDS
    paths, commonly mounted read-only (e.g. Docker's ``-v ...:/data:ro``),
    while the derivative copies are the writable ones this run actually owns.
    """
    metabolite_maps = {
        met: mrsi_derivative(config.derivative_dir, subject, session, space="mrsi", met=met, desc="signal", suffix_override="mrsi")
        for met in inputs.metabolite_maps
    }
    crlb_maps = {
        met: mrsi_derivative(config.derivative_dir, subject, session, space="orig", met=met, desc="crlb", suffix_override="mrsi")
        for met in inputs.crlb_maps
    }
    snr_map = (
        mrsi_derivative(config.derivative_dir, subject, session, space="orig", desc="snr", suffix_override="mrsi")
        if inputs.snr_map is not None
        else None
    )
    linewidth_map = (
        mrsi_derivative(config.derivative_dir, subject, session, space="orig", desc="fwhm", suffix_override="mrsi")
        if inputs.linewidth_map is not None
        else None
    )
    water_map = (
        mrsi_derivative(config.derivative_dir, subject, session, space="mrsi", met="water", desc="signal", suffix_override="mrsi")
        if inputs.water_map is not None
        else None
    )
    flip_angle_map = (
        mrsi_derivative(config.derivative_dir, subject, session, space="orig", desc="b1map", suffix_override="mrsi")
        if inputs.flip_angle_map is not None
        else None
    )
    return metabolite_maps, crlb_maps, snr_map, linewidth_map, water_map, flip_angle_map


def run_mrsi_load_workflow(config, subject: str, session: str | None, inputs: MRSIInputs, t1_path: Path | None = None) -> MRSILoadResult:
    """Load one recording's native-space MRSI maps.

    Copies raw inputs into the derivatives tree, optionally rigid-corrects
    their orientation against the T1w anatomical (see
    :func:`mrsiprep.mrsi.orientation.correct_mrsi_orientation`, opt-in via
    ``config.correct_mrsi_orientation``), and ensures a brainmask exists
    (deriving one from the water/metabolite maps if the input layout didn't
    provide one). Spike filtering, T1-saturation correction, and reference-
    image/quality-mask generation are separate steps (see
    :func:`run_spike_filter_workflow`/:func:`run_t1_water_correction_workflow`/
    :func:`run_mrsi_reference_workflow`/:func:`run_mrsi_quality_workflow`).

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param inputs: The recording's raw MRSI inputs as discovered by
        :func:`mrsiprep.io.loaders.load_mrsi_inputs` (metabolite/CRLB
        maps, SNR/linewidth/water/flip-angle maps, brainmask -- any of
        which may be ``None`` except ``metabolite_maps``).
    :param t1_path: The recording's registration-ready T1w anatomical.
        Required when ``config.correct_mrsi_orientation`` is set; unused
        otherwise.
    :returns: :class:`MRSILoadResult` with derivatives written to
        ``config.derivative_dir`` and referenced by path.
    """
    _copy_native_maps(config, subject, session, inputs)
    if config.correct_mrsi_orientation:
        if t1_path is None:
            raise ValueError("--correct-mrsi-orientation requires a T1w anatomical, but none was provided.")
        metabolite_maps, crlb_maps, snr_map, linewidth_map, water_map, flip_angle_map = _derivative_map_paths(config, subject, session, inputs)
        correct_mrsi_orientation(
            config,
            subject,
            session,
            metabolite_maps,
            t1_path,
            crlb_maps=crlb_maps,
            snr_map=snr_map,
            linewidth_map=linewidth_map,
            water_map=water_map,
            flip_angle_map=flip_angle_map,
        )
        # Everything downstream must read the corrected derivative copies,
        # not the (possibly misaligned, and possibly read-only) input paths
        # this run started from.
        inputs.metabolite_maps = metabolite_maps
        inputs.crlb_maps = crlb_maps
        inputs.snr_map = snr_map
        inputs.linewidth_map = linewidth_map
        inputs.water_map = water_map
        inputs.flip_angle_map = flip_angle_map
    brainmask = ensure_brainmask(config, subject, session, inputs.brainmask, inputs.water_map, inputs.metabolite_maps)
    return MRSILoadResult(
        raw_maps=inputs.metabolite_maps,
        brainmask=brainmask,
        crlb_maps=inputs.crlb_maps,
        snr_map=inputs.snr_map,
        linewidth_map=inputs.linewidth_map,
        water_map=inputs.water_map,
        flip_angle_map=inputs.flip_angle_map,
    )


def run_spike_filter_workflow(config, subject: str, session: str | None, load: MRSILoadResult) -> SpikeFilterResult:
    """Spike-detect and biharmonic-repair ``load.raw_maps``.

    A no-op pass-through when ``config.filter_biharmonic`` is ``False``
    (``--no-filter``): returns ``load.raw_maps`` itself, unchanged (see
    :func:`mrsiprep.mrsi.filtering.filter_metabolite_maps`).

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param load: This recording's :func:`run_mrsi_load_workflow` output.
    :returns: :class:`SpikeFilterResult`.
    """
    preproc = filter_metabolite_maps(config, subject, session, load.raw_maps, load.brainmask)
    return SpikeFilterResult(preproc_maps=preproc)


def run_t1_water_correction_workflow(
    config, subject: str, session: str | None, load: MRSILoadResult, filtered: SpikeFilterResult
) -> WaterCorrectionResult:
    """Apply (or skip) T1-saturation ("water") correction to ``filtered``'s
    spike-filtered metabolite maps.

    A no-op pass-through when ``config.t1_correction == "none"`` (the
    default): returns ``filtered.preproc_maps`` itself, unchanged. Otherwise
    applies :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction`
    (``"literature"``, nominal flip angle from ``mrsinmrs.json``) or
    :func:`mrsiprep.mrsi.t1_correction.apply_t1_correction_voxelwise`
    (``"voxelwise"``, a per-recording flip-angle/B1+ map).

    Runs entirely in MRSI-native space using only acquisition metadata and
    same-grid maps -- no dependency on anatomical prep or registration.

    .. note::
        The voxelwise path assumes ``load.flip_angle_map`` is already on
        the same grid as the metabolite maps (enforced only by a shape
        check, not a real spatial-alignment check) -- a known, separately
        tracked limitation, not addressed here.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param load: This recording's :func:`run_mrsi_load_workflow` output.
    :param filtered: This recording's :func:`run_spike_filter_workflow` output.
    :returns: :class:`WaterCorrectionResult`.
    """
    if config.t1_correction == "literature":
        mrsinmrs_resolved = resolve_mrsinmrs(config.mrsinmrs, subject, session)
        acquisition_params = resolve_acquisition_params(mrsinmrs_resolved)
        corrected, provenance, _ = apply_t1_correction(
            config, subject, session, filtered.preproc_maps, acquisition_params, config.t1_correction_water_status
        )
        return WaterCorrectionResult(corrected_maps=corrected, provenance=provenance)
    if config.t1_correction == "voxelwise":
        if load.flip_angle_map is None:
            raise ValueError(
                "--t1-correction voxelwise requires a per-recording flip-angle (B1+) map "
                "(desc-b1map in the MRSI input layout), but none was found for this recording. "
                "Use --t1-correction literature (nominal flip angle from mrsinmrs.json) or "
                "--t1-correction none instead."
            )
        mrsinmrs_resolved = resolve_mrsinmrs(config.mrsinmrs, subject, session)
        acquisition_params = resolve_acquisition_params(mrsinmrs_resolved)
        corrected, provenance, _ = apply_t1_correction_voxelwise(
            config, subject, session, filtered.preproc_maps, load.flip_angle_map, acquisition_params, config.t1_correction_water_status
        )
        return WaterCorrectionResult(corrected_maps=corrected, provenance=provenance)
    return WaterCorrectionResult(corrected_maps=filtered.preproc_maps, provenance=None)


def run_mrsi_reference_workflow(
    config, subject: str, session: str | None, load: MRSILoadResult, filtered: SpikeFilterResult, water: WaterCorrectionResult, inputs: MRSIInputs
) -> MRSIReferenceResult:
    """Build the reference-metabolite image from ``water``'s (possibly
    T1-corrected) maps, assembling the final :class:`MRSIReferenceResult`.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param load: This recording's :func:`run_mrsi_load_workflow` output.
    :param filtered: This recording's :func:`run_spike_filter_workflow` output.
    :param water: This recording's :func:`run_t1_water_correction_workflow` output.
    :param inputs: The same :class:`MRSIInputs` passed to
        :func:`run_mrsi_load_workflow` (``crlb_maps``/``snr_map``/
        ``linewidth_map`` may have been rebound there by orientation
        correction, so this must be the same, possibly-mutated object).
    :returns: :class:`MRSIReferenceResult` with all derivatives written to
        ``config.derivative_dir`` and referenced by path.
    """
    reference = generate_reference(config, subject, session, water.corrected_maps, preferred_met=config.ref_met)
    return MRSIReferenceResult(
        raw_maps=load.raw_maps,
        preproc_maps=filtered.preproc_maps,
        corrected_maps=water.corrected_maps,
        crlb_maps=inputs.crlb_maps,
        snr_map=inputs.snr_map,
        linewidth_map=inputs.linewidth_map,
        water_map=inputs.water_map,
        brainmask=load.brainmask,
        reference=reference,
        t1_correction_provenance=water.provenance,
        flip_angle_map=inputs.flip_angle_map,
    )


def run_mrsi_quality_workflow(
    config, subject: str, session: str | None, water: WaterCorrectionResult, inputs: MRSIInputs, brainmask: Path
) -> MRSIQualityResult:
    """Normalize the upstream tool's CRLB/SNR/linewidth units and build
    per-metabolite voxel-quality masks from ``water``'s (possibly
    T1-corrected) maps.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param water: This recording's :func:`run_t1_water_correction_workflow` output.
    :param inputs: The same :class:`MRSIInputs` passed to
        :func:`run_mrsi_load_workflow` (``crlb_maps``/``snr_map``/
        ``linewidth_map`` may have been rebound there by orientation
        correction, so this must be the same, possibly-mutated object).
    :param brainmask: This recording's :func:`run_mrsi_load_workflow` brainmask.
    :returns: :class:`MRSIQualityResult` with all derivatives written to
        ``config.derivative_dir`` and referenced by path.
    """
    qcmasks, qc_summary = make_quality_masks(
        config,
        subject,
        session,
        water.corrected_maps,
        inputs.crlb_maps,
        inputs.snr_map,
        inputs.linewidth_map,
        brainmask,
    )
    return MRSIQualityResult(qcmasks=qcmasks, qc_summary=qc_summary)
