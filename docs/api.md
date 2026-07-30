# API Reference

MRSIPrep is structured as a library of workflow-orchestration functions, one
per pipeline stage, invoked in sequence by
{py:func}`mrsiprep.workflows.participant.run_participant_workflow` -- the
same top-level entry point the CLI calls. Each stage function takes the
run's `config` object plus the outputs of earlier stages and returns a
small `dataclass` result that later stages consume.

This page documents the internal architecture for anyone extending
MRSIPrep or calling its stages directly from Python (`import mrsiprep`)
rather than through the CLI. For end-user usage and the full CLI flag
reference, see [Basic Usage](usage_basic.md).

## Configuration

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.config.settings
   mrsiprep.config.defaults
```

## Top-level orchestration

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.workflows.participant
   mrsiprep.workflows.base
```

## Pipeline stage workflows

Each module below wraps one pipeline stage (see the Workflow Architecture
section on the [home page](index.md) for the stage order) behind a single
`run_*_workflow` entry point.

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.workflows.anatomical
   mrsiprep.workflows.mrsi
   mrsiprep.workflows.tissue
   mrsiprep.workflows.registration
   mrsiprep.workflows.parcellation
   mrsiprep.workflows.connectivity
   mrsiprep.workflows.reports
```

## Registration

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.registration.mrsi_to_t1
   mrsiprep.registration.t1_to_mni
   mrsiprep.registration.subject_template
   mrsiprep.registration.transforms
```

## Backend interfaces

Thin wrappers around the external registration/segmentation tools
MRSIPrep shells out to or calls via Python bindings.

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.interfaces.ants
   mrsiprep.interfaces.fsl
   mrsiprep.interfaces.freesurfer
   mrsiprep.interfaces.chimera
```

## MRSI processing

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.mrsi.filtering
   mrsiprep.mrsi.masks
   mrsiprep.mrsi.quality
   mrsiprep.mrsi.reference
   mrsiprep.mrsi.resampling
   mrsiprep.mrsi.pvc
```

## Tissue segmentation

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.tissue.synthseg_fast
   mrsiprep.tissue.fuzzy_cmeans
   mrsiprep.tissue.fractions
   mrsiprep.tissue.psf
```

## Parcellation and connectivity

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.parcellation.synthseg
   mrsiprep.parcellation.chimera_native
   mrsiprep.parcellation.mni_atlas
   mrsiprep.parcellation.extraction
   mrsiprep.parcellation.tissue_regression
   mrsiprep.connectivity.export
   mrsiprep.connectivity.connectivity
```

## I/O

```{eval-rst}
.. autosummary::
   :toctree: _autosummary

   mrsiprep.io.bids
   mrsiprep.io.loaders
   mrsiprep.io.naming
   mrsiprep.io.derivatives
   mrsiprep.io.validators
   mrsiprep.io.mrsinmrs
```
