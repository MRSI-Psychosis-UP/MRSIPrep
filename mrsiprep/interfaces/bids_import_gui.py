"""Minimal optional GUI launcher for BIDS import."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    except ImportError as exc:
        raise SystemExit("PyQt6 is required for mrsiprep-import-gui. Use mrsiprep-import for CLI import.") from exc

    from mrsiprep.interfaces.bids_import import migrate_session_folder

    app = QApplication(sys.argv)
    source = QFileDialog.getExistingDirectory(None, "Choose source folder")
    if not source:
        return 1
    bids = QFileDialog.getExistingDirectory(None, "Choose BIDS root")
    if not bids:
        return 1
    subject, ok = _text_dialog("Subject", "Subject label without sub-:")
    if not ok:
        return 1
    session, ok = _text_dialog("Session", "Session label:")
    if not ok:
        return 1
    summary = migrate_session_folder(source, bids, subject=subject, session=session)
    QMessageBox.information(None, "MRSIPrep import", f"Imported MRSI={len(summary['mrsi'])}, T1={len(summary['t1'])}, CAT12={len(summary['cat12'])}, errors={len(summary['errors'])}")
    return 0


def _text_dialog(title: str, label: str):
    from PyQt6.QtWidgets import QInputDialog

    return QInputDialog.getText(None, title, label)


if __name__ == "__main__":
    raise SystemExit(main())
