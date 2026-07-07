"""Combine per-step QC HTML reports into a single chronological report."""

from __future__ import annotations

import re
from pathlib import Path

from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.reports.slices import STYLE

STEP_ORDER = ("tissue", "mrsi-preproc", "registration", "parcellation", "connectivity")

_BODY_RE = re.compile(r"<body>(.*)</body>", re.S)


def combine_qc_reports(config, subject: str, session: str | None) -> Path | None:
    """Concatenate the per-step QC HTML reports (in pipeline order) into one
    file, then delete the individual per-step files. Steps whose report was
    never generated (e.g. skipped stage) are silently omitted.
    """
    combined = qc_report_derivative(config.derivative_dir, subject, session, "combined")
    step_paths = [qc_report_derivative(config.derivative_dir, subject, session, step) for step in STEP_ORDER]
    existing = [path for path in step_paths if path.exists()]
    if not existing:
        return None

    sections = []
    for path in existing:
        match = _BODY_RE.search(path.read_text(encoding="utf-8"))
        sections.append(match.group(1).strip() if match else "")

    title = f"MRSIPrep QC report: sub-{subject}" + (f" ses-{session}" if session else "")
    body = "\n<hr>\n".join(sections)
    combined.write_text(
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>" + title + "</title>\n"
        f"<style>{STYLE}</style>\n"
        "</head>\n"
        "<body>\n" + body + "\n</body></html>",
        encoding="utf-8",
    )

    for path in existing:
        path.unlink()

    return combined
