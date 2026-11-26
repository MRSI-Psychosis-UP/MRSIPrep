"""Nipype-based orchestration engine for the participant workflow.

This is the sole participant-workflow engine. It wraps the shared ``_step_*``
step functions as Nipype nodes and connects them into a per-recording DAG,
giving node caching (skip unchanged steps on rerun) and cross-recording
parallelism, while writing the same BIDS derivatives and emitting the same Rich
``Debug`` UX. ``run_participant_workflow`` delegates here after validation.
"""

from __future__ import annotations

from mrsiprep.workflows.nipype_engine.run import execute_recordings_nipype

__all__ = ["execute_recordings_nipype"]
