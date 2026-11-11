"""Report workflow."""

from __future__ import annotations

from mrsiprep.reports.html import generate_subject_report
from mrsiprep.reports.overview import update_report_overview
from mrsiprep.utils.debug import Debug


def run_reports_workflow(config, subject, session, outputs, qc_sections=None):
    """Generate the per-recording HTML quality-control report.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param outputs: Dict of this recording's output paths (as accumulated
        across earlier workflow stages); recognized keys include
        ``"qc_summary"`` and ``"regional_table"``, each embedded as an
        HTML table when present.
    :param qc_sections: Dict of per-stage QC section lists (each a list of
        ``(heading, body_html)`` tuples, as returned by the
        ``build_*_qc_sections`` functions in :mod:`mrsiprep.reports`),
        folded into the report's tabs alongside ``outputs``.
    :returns: Path to the generated HTML report.
    """
    report = generate_subject_report(config, subject, session, outputs, qc_sections or {})
    try:
        update_report_overview(config)
    except Exception as exc:  # noqa: BLE001 -- the per-recording report above must not be lost over this
        Debug(verbose=config.verbose).warning(f"Could not update report_overview.html: {exc}")
    return report
