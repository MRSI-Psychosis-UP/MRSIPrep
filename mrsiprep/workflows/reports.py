"""Report workflow."""

from __future__ import annotations

from mrsiprep.reports.html import generate_subject_report


def run_reports_workflow(config, subject, session, outputs):
    """Generate the per-recording HTML quality-control report."""
    return generate_subject_report(config, subject, session, outputs)
