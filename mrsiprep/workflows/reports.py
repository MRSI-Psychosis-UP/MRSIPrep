"""Report workflow."""

from __future__ import annotations

from mrsiprep.reports.html import generate_subject_report


def run_reports_workflow(config, subject, session, outputs):
    """Generate the per-recording HTML quality-control report.

    :param config: Run-wide :class:`mrsiprep.config.settings.MRSIPrepConfig`.
    :param subject: BIDS subject label, without the ``sub-`` prefix.
    :param session: BIDS session label without the ``ses-`` prefix, or
        ``None`` for session-less datasets.
    :param outputs: Dict of this recording's output paths (as accumulated
        across earlier workflow stages); recognized keys include
        ``"qc_summary"`` and ``"regional_table"``, each embedded as an
        HTML table when present.
    :returns: Path to the generated HTML report.
    """
    return generate_subject_report(config, subject, session, outputs)
