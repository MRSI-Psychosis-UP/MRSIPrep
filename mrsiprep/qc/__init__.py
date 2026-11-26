"""Quality-control measures computed from MRSIPrep's outputs.

Each QC feature is one module in this package. The modules compute; they do
not plot or write HTML. Rendering lives in :mod:`mrsiprep.reports`, and the
call from the pipeline lives in :mod:`mrsiprep.workflows.steps`. Keeping the
three apart means a measure can be called on its own (from a notebook, a batch
script or a test) with the same code the report uses.

Conventions for a QC module:

- Compute functions take plain inputs (file paths, arrays, transform lists)
  and return a small dataclass with the result. Avoid requiring the run
  config; where the pipeline needs one, add a thin wrapper that resolves
  paths from it and calls the plain function.
- Optional inputs that are missing (an atlas, a segmentation, a transform)
  make the function return ``None`` rather than raise, so a missing extra
  never fails a run.
- Tables go to the recording's ``confounds/`` folder as
  ``desc-<name>`` TSVs, through :func:`mrsiprep.io.naming.mrsi_derivative`;
  add ``<name>`` to ``_CONFOUND_DESCS`` in :mod:`mrsiprep.io.naming`.
- Thresholds that turn a number into pass/fail are module-level constants,
  with a comment on where the value comes from.

Features:

- :mod:`mrsiprep.qc.ventricles` -- are the lateral ventricles visible where
  they should be in each metabolite map (detection + Dice with the subject's
  own ventricles).

See "Adding a QC feature" in ``docs/extending.md``.
"""
