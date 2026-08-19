"""Combined, tabbed HTML report: the single per-recording QC/report page.

Assembles both the top-level coverage/QC summary tables and the per-stage
QC sections (tissue segmentation, spike filtering, T1 correction,
registration alignment, parcellation, connectivity) previously split across
several standalone HTML pages under ``reports/qc-reports/`` -- see
``build_*_qc_sections`` in each ``mrsiprep.reports.*`` module for how each
stage's sections are produced.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mrsiprep.io.mrsinmrs import load_mrsinmrs, resolve_mrsinmrs
from mrsiprep.io.naming import coverage_report_html
from mrsiprep.reports.preproc_overview import build_preproc_overview_sections
from mrsiprep.reports.registration_overview import leakage_table_html

_MRSINMRS_URL = "https://pubmed.ncbi.nlm.nih.gov/33559967/"

_TAB_STYLE = (
    ".tabs{display:flex;gap:0.25rem;border-bottom:2px solid #ddd;margin-bottom:1rem;flex-wrap:wrap}"
    ".tab-button{padding:0.5rem 1rem;border:1px solid #ddd;border-bottom:none;background:#f3f3f3;"
    "cursor:pointer;border-radius:4px 4px 0 0;font-size:0.95rem}"
    ".tab-button.active{background:#fff;font-weight:bold;border-bottom:2px solid #fff;margin-bottom:-2px}"
    ".tab-panel{display:none}"
    ".tab-panel.active{display:block}"
    ".dag-chain{font-family:monospace;line-height:2.2;word-spacing:0.3em}"
    ".dag-node{background:#eef;border:1px solid #99c;border-radius:4px;padding:0.15rem 0.5rem}"
)

_TAB_SCRIPT = """
<script>
function showTab(id) {
  document.querySelectorAll('.tab-panel').forEach(function (panel) {
    panel.classList.toggle('active', panel.id === id);
  });
  document.querySelectorAll('.tab-button').forEach(function (button) {
    button.classList.toggle('active', button.dataset.tab === id);
  });
}
</script>
"""


def generate_subject_report(config, subject: str, session: str | None, outputs: dict, qc_sections: dict | None = None) -> Path:
    qc_sections = qc_sections or {}
    out = coverage_report_html(config.derivative_dir, subject, session)
    out.parent.mkdir(parents=True, exist_ok=True)

    qc_html = ""
    qc_path = outputs.get("qc_summary")
    if qc_path and Path(qc_path).exists():
        qc_html = pd.read_csv(qc_path, sep="\t").to_html(index=False, border=0)

    regional_html = ""
    regional = outputs.get("regional_table")
    if regional and Path(regional).exists():
        regional_html = pd.read_csv(regional, sep="\t").head(50).to_html(index=False, border=0)

    parcel_qc_html = ""
    parcel_qc_summary = ""
    parcel_qc = outputs.get("parcel_qc")
    if parcel_qc and Path(parcel_qc).exists():
        parcel_df = pd.read_csv(parcel_qc, sep="\t")
        overview = (
            parcel_df.groupby(["parcel_id", "parcel_name", "hemisphere"], dropna=False)
            .agg(
                anatomical_coverage_percent=("anatomical_coverage_percent", "first"),
                mean_crlb=("mean_crlb", "mean"),
                qc_valid_fraction=("qc_valid_fraction", "mean"),
            )
            .reset_index()
            .sort_values("anatomical_coverage_percent")
        )
        parcel_qc_html = overview.to_html(index=False, border=0, float_format=lambda value: f"{value:.3f}")
        parcel_qc_summary = (
            f"<p>Mean anatomical MRSI coverage: <strong>{overview['anatomical_coverage_percent'].mean():.1f}%</strong>; "
            f"mean parcel CRLB: <strong>{parcel_df['mean_crlb'].mean():.2f}</strong>.</p>"
        )

    leakage_df = None
    leakage_qc = outputs.get("leakage_qc")
    if leakage_qc and Path(leakage_qc).exists():
        leakage_df = pd.read_csv(leakage_qc, sep="\t")

    mrsi_qc_body = qc_html or "<p>No QC table available.</p>"
    mrsi_raw_sections = qc_sections.get("mrsi_raw")
    if mrsi_raw_sections:
        mrsi_qc_body += "<h3>Raw metabolite maps (pre-pipeline)</h3>" + _sections_html(mrsi_raw_sections)

    tabs: list[tuple[str, str, str]] = [
        ("acquisition", "MRSinMRS", _mrsinmrs_html(config, subject, session)),
        ("mrsi-raw-qc", "MRSI Raw QC", mrsi_qc_body),
        ("preproc", "Preproc", _sections_html(build_preproc_overview_sections(config))),
        ("anatomical", "Anatomical", _sections_html(qc_sections.get("tissue"))),
        ("spike-filter", "Spike filter", _sections_html(qc_sections.get("mrsi_preproc"))),
    ]

    t1_correction_sections = qc_sections.get("t1_correction")
    if t1_correction_sections is not None:
        tabs.append(("t1-correction", "T1 correction", _sections_html(t1_correction_sections)))

    tabs.append((
        "t1w-alignment",
        "T1w-space alignment",
        _sections_html(qc_sections.get("t1w_alignment")) + leakage_table_html(leakage_df, "T1w"),
    ))
    tabs.append((
        "coverage",
        "Coverage &amp; Alignment",
        parcel_qc_summary + _parcel_figures_html(out.parent) + (parcel_qc_html or "<p>No parcelwise QC table available.</p>"),
    ))
    tabs.append((
        "mni-alignment",
        "MNI-space alignment",
        _sections_html(qc_sections.get("mni_alignment")) + leakage_table_html(leakage_df, "MNI152NLin2009cAsym"),
    ))
    tabs.append(("parcellation", "Parcellation", _sections_html(qc_sections.get("parcellation"))))

    connectivity_sections = qc_sections.get("connectivity")
    if connectivity_sections is not None:
        tabs.append(("connectivity", "Connectivity", _sections_html(connectivity_sections)))

    tabs.append(("runtime", "Runtime", _sections_html(qc_sections.get("runtime"))))
    tabs.append(("outputs", "Outputs", _outputs_html(outputs)))

    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>MRSIPrep sub-" + subject + (f" ses-{session}" if session else "") + "</title>",
        "<style>body{font-family:Arial,sans-serif;margin:2rem;line-height:1.4}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 8px}code{background:#f3f3f3;padding:2px 4px}"
        "img{max-width:100%;border:1px solid #ddd}.row{display:flex;gap:0.5rem;flex-wrap:wrap}.row>div{flex:1 1 240px}.col{display:flex;flex-direction:column;gap:1rem}"
        + _TAB_STYLE
        + "</style>",
        "</head><body>",
        f"<h1>MRSIPrep report: sub-{subject}" + (f" ses-{session}" if session else "") + "</h1>",
        "<h2>Inputs</h2>",
        f"<p>BIDS directory: <code>{config.bids_dir}</code></p>",
        f"<p>Output directory: <code>{config.derivative_dir}</code></p>",
        f"<p>Processing mode: <code>{config.processing_mode}</code></p>",
        "<div class='tabs'>",
    ]
    lines.extend(
        f"<button class='tab-button{' active' if index == 0 else ''}' data-tab='{tab_id}' "
        f"onclick=\"showTab('{tab_id}')\">{label}</button>"
        for index, (tab_id, label, _) in enumerate(tabs)
    )
    lines.append("</div>")
    lines.extend(
        f"<div class='tab-panel{' active' if index == 0 else ''}' id='{tab_id}'><h2>{label}</h2>{body}</div>"
        for index, (tab_id, label, body) in enumerate(tabs)
    )
    lines.append("<h2>Citations</h2>")
    lines.append(_citations_html(config))
    lines.append(_TAB_SCRIPT)
    lines.extend(["</body></html>"])
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _sections_html(sections: list[tuple[str, str]] | None) -> str:
    if not sections:
        return "<p>Not available for this configuration.</p>"
    return "\n".join(f"<h3>{heading}</h3>{body}" for heading, body in sections)


def _outputs_html(outputs: dict) -> str:
    items = "".join(f"<li><strong>{key}</strong>: <code>{value}</code></li>" for key, value in sorted(outputs.items()))
    return f"<ul>{items}</ul>"


_MRSINMRS_UNITS: dict[str, str] = {
    "TE": "s",
    "RepetitionTime": "s",
    "TR": "s",
    "FlipAngle": "°",
    "ExcitationFlipAngle": "°",
    "MagneticFieldStrength": "T",
    "FieldStrength": "T",
    "RotationDeg": "°",
    "SlabThicknessMM": "mm",
    "SpectralBandwidthHz": "Hz",
    "AcquisitionDurationMS": "ms",
    "WaterReferenceTE": "s",
    "WaterReferenceTR": "s",
    "WaterReferenceFlipAngle": "°",
    "WaterSupprBWHz": "Hz",
    "DeltaFrequencyPPM": "ppm",
    "FOV": "mm",
    "ResolutionMM3": "mm",
    "WaterReferenceResolutionMM3": "mm",
}


def _mrsinmrs_html(config, subject: str, session: str | None) -> str:
    """MRSI acquisition/hardware/reconstruction parameters, per the MRSinMRS
    minimum reporting standard (Lin et al. 2021), read from an optional
    dataset-level mrsinmrs.json. Absent by default -- this is opt-in
    metadata, not a required input."""
    try:
        parsed = load_mrsinmrs(config.bids_dir)
    except ValueError as exc:
        return f"<p>Could not read mrsinmrs.json: {exc}</p>"
    resolved = resolve_mrsinmrs(parsed, subject, session)
    if not resolved:
        return (
            f"<p>No <code>mrsinmrs.json</code> found at the BIDS root. Consider adding one to report "
            f"MRSI acquisition parameters per the <a href='{_MRSINMRS_URL}'>MRSinMRS</a> minimum reporting "
            "standard (Lin et al. 2021).</p>"
        )
    rows = []
    for key in sorted(resolved):
        if key == "SequenceCitation":
            continue
        unit = _MRSINMRS_UNITS.get(key, "")
        rows.append(f"<tr><td>{key}</td><td>{resolved[key]}</td><td>{unit}</td></tr>")
    table = "<table><tr><th>Parameter</th><th>Value</th><th>Unit</th></tr>" + "".join(rows) + "</table>"
    citation = resolved.get("SequenceCitation")
    citation_html = f"<p>Sequence reference: {citation}</p>" if citation else ""
    return table + citation_html


def _citations_html(config) -> str:
    parts = [
        "<p>MRSIPrep: see <code>CITATION.cff</code> in the "
        "<a href='https://github.com/MRSI-Psychosis-UP/MRSIPrep'>MRSIPrep repository</a> for how to cite this "
        "software.</p>",
        f"<p>MRSI acquisition reporting follows the <a href='{_MRSINMRS_URL}'>MRSinMRS</a> minimum reporting "
        "standard (Lin et al. 2021).</p>",
    ]
    citation = getattr(config, "preset_citation", None)
    if citation:
        text = citation.get("text", citation.get("label", ""))
        url = citation.get("url") or (f"https://doi.org/{citation['doi']}" if citation.get("doi") else None)
        cited = f"<a href='{url}'>{text}</a>" if url else text
        parts.append(f"<p>Processing parameters replicate: {cited}</p>")
    return "\n".join(parts)


def _parcel_figures_html(report_dir: Path) -> str:
    """Embed the parcelwise coverage + per-metabolite CRLB-quality PNGs that
    live in the report's figures/ subfolder (relative <img> paths)."""
    figures_dir = report_dir / "figures"
    parts: list[str] = []
    coverage = sorted(figures_dir.glob("*desc-parcelcoverage*.png"))
    if coverage:
        parts.append("<h3>MRSI anatomical coverage</h3>")
        parts.append(f"<div><img src='figures/{coverage[0].name}' alt='parcelwise coverage'></div>")
    crlb = sorted(figures_dir.glob("*desc-parcelcrlbquality*.png"))
    if crlb:
        parts.append(f"<h3>Parcelwise CRLB quality (green reliable / red unreliable), {len(crlb)} metabolites</h3>")
        parts.append("<div class='row'>")
        parts.extend(f"<div><img src='figures/{path.name}' alt='{path.stem}'></div>" for path in crlb)
        parts.append("</div>")
    return "\n".join(parts) if parts else ""
