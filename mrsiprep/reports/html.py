"""Combined, tabbed HTML report: the single per-recording QC/report page.

Assembles both the top-level coverage/QC summary tables and the per-stage
QC sections (tissue segmentation, spike filtering, T1 correction,
registration alignment, parcellation, connectivity) previously split across
several standalone HTML pages under ``reports/qc-reports/`` -- see
``build_*_qc_sections`` in each ``mrsiprep.reports.*`` module for how each
stage's sections are produced.
"""

from __future__ import annotations

import json
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
    "table.sortable th{cursor:pointer;user-select:none;white-space:nowrap}"
    "table.sortable th:hover{background:#eef}"
    "table.sortable th::after{content:' \\2195';color:#aaa;font-size:0.8em}"
    "pre.filetree{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:0.85rem;line-height:1.45;"
    "background:#fafafa;border:1px solid #eee;padding:0.75rem;overflow-x:auto}"
    "ul.filetree{list-style:none;padding-left:1rem;margin:0.2rem 0}"
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

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var head = table.tHead;
    if (!head) { return; }
    Array.prototype.forEach.call(head.rows[0].cells, function (th, index) {
      th.addEventListener('click', function () {
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        var ascending = !(th.dataset.sortAsc === 'true');
        rows.sort(function (a, b) {
          var x = a.cells[index].textContent.trim();
          var y = b.cells[index].textContent.trim();
          var nx = parseFloat(x), ny = parseFloat(y);
          var numeric = !isNaN(nx) && !isNaN(ny) && x !== '' && y !== '';
          var cmp = numeric ? nx - ny : x.localeCompare(y);
          return ascending ? cmp : -cmp;
        });
        rows.forEach(function (row) { body.appendChild(row); });
        Array.prototype.forEach.call(head.rows[0].cells, function (other) {
          delete other.dataset.sortAsc;
        });
        th.dataset.sortAsc = ascending ? 'true' : 'false';
      });
    });
  });
});
</script>
"""


def _build_tabs(config, subject, session, out, outputs, qc_sections, mrsi_qc_body,
                leakage_df, parcel_qc_summary, parcel_qc_html, regional_html):
    """Assemble the (id, label, body) tabs in pipeline order.

    Split out of generate_subject_report: the tab list is the part that
    changes whenever the report is reorganised, and inlining it pushed that
    function past the project's complexity limits.
    """
    pvc_sections = qc_sections.get("mrsi_pvc")
    t1_correction_sections = qc_sections.get("t1_correction")
    connectivity_sections = qc_sections.get("connectivity")

    # Order is deliberate and follows the pipeline: raw signal, then what was
    # done to it, then where it was put, then what was measured from it.
    tabs: list[tuple[str, str, str]] = [
        ("mrsi-raw-qc", "MRSI Raw QC", mrsi_qc_body),
    ]
    if pvc_sections is not None:
        tabs.append(("mrsi-pvc", "MRSI PVC", _sections_html(pvc_sections)))
    tabs.append(("spike-filter", "Spike Filter", _sections_html(qc_sections.get("mrsi_preproc"))))
    if t1_correction_sections is not None:
        tabs.append(("t1-correction", "T1 correction", _sections_html(t1_correction_sections)))
    tabs.append(("anatomical", "Anatomical", _sections_html(qc_sections.get("tissue"))))
    tabs.append((
        "t1w-alignment",
        "T1-space alignment",
        _sections_html(qc_sections.get("t1w_alignment")) + leakage_table_html(leakage_df, "T1w"),
    ))
    tabs.append((
        "mni-alignment",
        "Template-space alignment",
        _sections_html(qc_sections.get("mni_alignment")) + leakage_table_html(leakage_df, "MNI152NLin2009cAsym"),
    ))
    tabs.append((
        "coverage",
        "Coverage",
        _parcel_figures_html(out.parent) + parcel_qc_summary
        + (parcel_qc_html or "<p>No parcelwise QC table available.</p>"),
    ))
    tabs.append(("parcellation", "Parcellation", _sections_html(qc_sections.get("parcellation")) + regional_html))
    if connectivity_sections is not None:
        tabs.append(("connectivity", "Connectivity", _sections_html(connectivity_sections)))
    tabs.append(("acquisition", "MRSinMRS", _mrsinmrs_html(config, subject, session)))
    tabs.append(("preproc", "PrepParams", _sections_html(build_preproc_overview_sections(config))))
    tabs.append(("runtime", "Runtime", _sections_html(qc_sections.get("runtime"))))
    tabs.append(("outputs", "Outputs", _outputs_html(outputs, out.parent.parent.parent)))
    return tabs


def generate_subject_report(config, subject: str, session: str | None, outputs: dict, qc_sections: dict | None = None) -> Path:
    qc_sections = qc_sections or {}
    out = coverage_report_html(config.derivative_dir, subject, session)
    out.parent.mkdir(parents=True, exist_ok=True)

    qc_html = ""
    qc_path = outputs.get("qc_summary")
    if qc_path and Path(qc_path).exists():
        qc_html = pd.read_csv(qc_path, sep="\t").to_html(index=False, border=0)

    regional_html = _regional_tables_html(outputs)

    parcel_qc_html = ""
    parcel_qc_summary = ""
    parcel_qc = outputs.get("parcel_qc")
    if parcel_qc and Path(parcel_qc).exists():
        parcel_df = pd.read_csv(parcel_qc, sep="\t")
        overview = (
            parcel_df.groupby(["parcel_id", "parcel_name", "hemisphere"], dropna=False)
            .agg(
                mean_crlb=("mean_crlb", "mean"),
                qc_valid_fraction=("qc_valid_fraction", "mean"),
            )
            .reset_index()
            .sort_values("qc_valid_fraction")
        )
        parcel_qc_html = _sortable_table(
            overview.to_html(index=False, border=0, float_format=lambda value: f"{value:.3f}")
        )
        # State the thresholds rather than the fraction alone: qc_valid_fraction
        # is meaningless without knowing what a voxel had to pass.
        parcel_qc_summary = _qc_threshold_note(config)

    leakage_df = None
    leakage_qc = outputs.get("leakage_qc")
    if leakage_qc and Path(leakage_qc).exists():
        leakage_df = pd.read_csv(leakage_qc, sep="\t")

    mrsi_qc_body = qc_html or "<p>No QC table available.</p>"
    mrsi_raw_sections = qc_sections.get("mrsi_raw")
    if mrsi_raw_sections:
        mrsi_qc_body += "<h3>Raw metabolite maps (pre-pipeline)</h3>" + _sections_html(mrsi_raw_sections)

    project_name = _bids_project_name(config)
    tabs = _build_tabs(
        config, subject, session, out, outputs, qc_sections, mrsi_qc_body,
        leakage_df, parcel_qc_summary, parcel_qc_html, regional_html,
    )

    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>MRSIPrep " + project_name + " sub-" + subject
        + (f" ses-{session}" if session else "") + "</title>",
        "<style>body{font-family:Arial,sans-serif;margin:2rem;line-height:1.4}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px 8px}code{background:#f3f3f3;padding:2px 4px}"
        "img{max-width:100%;border:1px solid #ddd}.row{display:flex;gap:0.5rem;flex-wrap:wrap}.row>div{flex:1 1 240px}.col{display:flex;flex-direction:column;gap:1rem}"
        + _TAB_STYLE
        + "</style>",
        "</head><body>",
        f"<h1>MRSIPrep report: {project_name} &middot; sub-{subject}"
        + (f" ses-{session}" if session else "")
        + "</h1>",
        "<h2>Inputs</h2>",
        f"<p>BIDS directory: <code>{config.bids_dir}</code></p>",
        f"<p>Output directory: <code>{config.derivative_dir}</code></p>",
        f"<p>Parcellation mode: <code>{config.parcellation_mode}</code></p>",
        f"<p>Tissue backend: <code>{config.tissue_backend}</code></p>",
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


def _qc_threshold_note(config) -> str:
    """Spell out the per-voxel thresholds behind ``qc_valid_fraction``.

    Only the metrics this run actually had are listed: a threshold on a map
    that was never supplied was never applied, and printing it would imply a
    filter that did not happen.
    """
    applied = [metric.strip().lower() for metric in (getattr(config, "quality_metrics", None) or [])]
    parts = []
    for metric, attribute, template in (
        ("crlb", "crlb_max", "CRLB &le; {}%"),
        ("snr", "snr_min", "SNR &ge; {}"),
        ("linewidth", "linewidth_max", "linewidth &le; {}"),
    ):
        if applied and metric not in applied:
            continue
        value = getattr(config, attribute, None)
        if value is not None:
            parts.append(template.format(value))
    criteria = ", ".join(parts) if parts else "no per-voxel quality thresholds"
    return (
        "<p><code>qc_valid_fraction</code> is the fraction of a parcel's MRSI voxels that passed "
        f"every per-voxel quality threshold in force for this run ({criteria}), averaged over "
        "metabolites. Rows are ordered worst first.</p>"
    )


def _sortable_table(table_html: str) -> str:
    """Tag a pandas-rendered table so the report's own click-to-sort works.

    Merges into the existing class attribute rather than adding a second one:
    two ``class=`` attributes on a tag is invalid HTML and browsers keep only
    the first, which silently dropped pandas' own ``dataframe`` class.
    """
    if 'class="dataframe"' in table_html:
        return table_html.replace('class="dataframe"', 'class="dataframe sortable"', 1)
    if "class='dataframe'" in table_html:
        return table_html.replace("class='dataframe'", "class='dataframe sortable'", 1)
    if "<table " in table_html:
        return table_html.replace("<table ", "<table class='sortable' ", 1)
    return table_html.replace("<table>", "<table class='sortable'>", 1)


def _bids_project_name(config) -> str:
    """Dataset name from the BIDS dataset_description.json, else the folder name."""
    try:
        description = Path(config.bids_dir) / "dataset_description.json"
        if description.exists():
            name = json.loads(description.read_text()).get("Name")
            if str(name or "").strip():
                return str(name).strip()
    except Exception:
        pass
    return Path(config.bids_dir).name


def _regional_tables_html(outputs: dict) -> str:
    """Preview of each parcellation's regional metabolite table.

    Uses the structured ``parcellations`` list when present (one entry per
    comma-separated scheme/scale/atlas), falling back to the singular
    ``regional_table`` key for runs that predate it.
    """
    entries = outputs.get("parcellations")
    if not entries:
        regional = outputs.get("regional_table")
        entries = [{"id": None, "regional_table": regional}] if regional else []

    blocks = []
    for entry in entries:
        table = entry.get("regional_table")
        if not table or not Path(table).exists():
            continue
        preview = pd.read_csv(table, sep="\t").head(50).to_html(index=False, border=0)
        heading = f"<h3>Regional metabolites: {entry['id']}</h3>" if entry.get("id") else "<h3>Regional metabolites</h3>"
        blocks.append(heading + preview)
    return "".join(blocks)


def _sections_html(sections: list[tuple[str, str]] | None) -> str:
    if not sections:
        return "<p>Not available for this configuration.</p>"
    return "\n".join(f"<h3>{heading}</h3>{body}" for heading, body in sections)


#: Left out of the Outputs tree: the report and its figures are what the reader
#: is already looking at, and they outnumber every real derivative several times
#: over, which buried the outputs the tree exists to show.
_OUTPUTS_TREE_SKIP = ("reports",)


def _outputs_html(outputs: dict, root: Path | None = None) -> str:
    """Derivative tree for this recording, in the shape ``tree`` prints.

    Walks the recording's own output directory rather than listing the
    ``outputs`` dict: the dict holds only the paths the workflow happened to
    register, while the reader wants to see what is actually on disk. Falls
    back to the registered paths when the directory is unavailable.
    """
    if root is not None and Path(root).is_dir():
        lines = _tree_lines(Path(root))
        if lines:
            body = "\n".join([f"{Path(root).name}/"] + lines)
            return f"<pre class='filetree'>{body}</pre>"
    return _outputs_fallback_html(outputs)


def _tree_lines(directory: Path, prefix: str = "") -> list[str]:
    """``tree``-style lines, directories first then files, each sorted."""
    try:
        entries = [entry for entry in directory.iterdir() if entry.name not in _OUTPUTS_TREE_SKIP]
    except OSError:
        return []
    directories = sorted((entry for entry in entries if entry.is_dir()), key=lambda e: e.name.lower())
    files = sorted((entry for entry in entries if not entry.is_dir()), key=lambda e: e.name.lower())
    ordered = directories + files

    lines: list[str] = []
    for index, entry in enumerate(ordered):
        last = index == len(ordered) - 1
        connector = "\u2514\u2500\u2500 " if last else "\u251c\u2500\u2500 "
        lines.append(f"{prefix}{connector}{entry.name}" + ("/" if entry.is_dir() else ""))
        if entry.is_dir():
            lines.extend(_tree_lines(entry, prefix + ("    " if last else "\u2502   ")))
    return lines


def _outputs_fallback_html(outputs: dict) -> str:
    entries = [(key, Path(str(value))) for key, value in outputs.items() if str(value or "").strip()]
    if not entries:
        return "<p>No outputs recorded.</p>"
    items = "".join(
        f"<li><code>{path}</code> <em>({key})</em></li>" for key, path in sorted(entries, key=lambda i: str(i[1]))
    )
    return f"<ul class='filetree'>{items}</ul>"


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
    return table


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
    # Exclude any "_met-" figure: those are the superseded one-row-per-file
    # renders, and a stale one left in figures/ by an earlier run would
    # otherwise be embedded alongside the grid that replaced it.
    crlb = sorted(
        path for path in figures_dir.glob("*desc-parcelcrlbquality*.png") if "_met-" not in path.name
    )
    if crlb:
        parts.append("<h3>Parcelwise CRLB quality (green reliable / red unreliable)</h3>")
        # Full width, stacked: the flex row this used to use squeezed each
        # metabolite to a 240px column, which is unreadable at 10 slices wide.
        parts.extend(f"<div><img src='figures/{path.name}' alt='{path.stem}'></div>" for path in crlb)
    return "\n".join(parts) if parts else ""
