"""Connectivity matrix QC report."""

from __future__ import annotations

from pathlib import Path

from mrsiprep.io.naming import qc_report_derivative
from mrsiprep.reports.slices import html_page


def write_connectivity_qc_report(
    config,
    subject: str,
    session: str | None,
    matrix_tsv_path: Path | None,
) -> Path:
    out = qc_report_derivative(config.derivative_dir, subject, session, "connectivity")
    out.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = out.parent / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    sections: list[tuple[str, str]] = []
    if matrix_tsv_path is not None and Path(matrix_tsv_path).exists():
        import matplotlib.pyplot as plt
        import pandas as pd

        matrix = pd.read_csv(matrix_tsv_path, sep="\t", index_col=0)
        fig, ax = plt.subplots(figsize=(max(6, 0.25 * len(matrix)), max(5, 0.25 * len(matrix))))
        image = ax.imshow(matrix.to_numpy(), cmap="coolwarm", vmin=-1, vmax=1)
        ax.set_xticks(range(len(matrix.columns)))
        ax.set_xticklabels(matrix.columns, rotation=90, fontsize=6)
        ax.set_yticks(range(len(matrix.index)))
        ax.set_yticklabels(matrix.index, fontsize=6)
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        matrix_png = figures_dir / f"{out.stem}_matrix.png"
        fig.savefig(matrix_png)
        plt.close(fig)
        sections.append((f"Connectivity matrix ({config.connectivity_method})", f"<img src='figures/{matrix_png.name}'>"))
    else:
        sections.append(("Connectivity matrix", "<p>Connectivity matrix not requested (--write-connectivity).</p>"))

    out.write_text(html_page(f"Connectivity QC: sub-{subject}" + (f" ses-{session}" if session else ""), sections), encoding="utf-8")
    return out
