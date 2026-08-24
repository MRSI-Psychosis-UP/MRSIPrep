# syntax=docker/dockerfile:1.7

ARG DEPS_IMAGE=mrsiprep-deps:cpu
FROM ${DEPS_IMAGE}

LABEL org.opencontainers.image.title="MRSIPrep"
LABEL org.opencontainers.image.description="BIDS App for preprocessing quantified whole-brain MRSI derivatives"
LABEL org.opencontainers.image.licenses="CHUV academic non-commercial research license"

WORKDIR /opt/mrsiprep
COPY pyproject.toml README.md LICENSE ./
COPY mrsiprep ./mrsiprep
COPY docker/entrypoint.sh /usr/local/bin/mrsiprep-entrypoint
RUN chmod 0755 /usr/local/bin/mrsiprep-entrypoint

# External and Python dependencies already live in DEPS_IMAGE. Rebuilding this
# thin layer updates MRSIPrep without rebuilding FreeSurfer/FSL/ANTs.
# nipype (pure-Python; drives the workflow engine) is installed here as well so
# existing dependency images built before it was added still get it without a
# full deps rebuild; it is a no-op once the deps image already ships it.
RUN /usr/bin/python3 -m pip install "nipype>=1.8" \
    && /usr/bin/python3 -m pip install --no-deps --force-reinstall .

# Reference templates come from TemplateFlow (see mrsiprep/config/templates.py
# for why). TemplateFlow fetches on demand by default, which would make runs
# depend on network access and on *when* they ran; pre-fetching every template
# MRSIPrep supports keeps the image self-contained and reproducible. Pin
# TEMPLATEFLOW_HOME so the cache is found at a fixed path regardless of $HOME.
#
# Keep this list in sync with SUPPORTED_TEMPLATES in config/templates.py --
# adding a template there without adding it here yields an image that reaches
# for the network mid-run (or fails offline).
ENV TEMPLATEFLOW_HOME=/opt/templateflow
RUN /usr/bin/python3 -c "\
import templateflow.api as api; \
[api.get('MNI152NLin2009cAsym', resolution=r, desc=d, suffix=s, extension='.nii.gz') \
 for r in (1, 2) for d, s in ((None, 'T1w'), ('brain', 'mask'))]" \
    && chmod -R a+rX /opt/templateflow

# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
# Intentionally root: entrypoint.sh runs the pipeline as root, then chowns the
# bind-mounted output directory back to HOST_UID/HOST_GID before exiting, so
# host-side output files aren't left root-owned. Dropping to a non-root USER
# here would break that chown-back step against arbitrary bind-mount owners.
ENTRYPOINT ["mrsiprep-entrypoint"]
