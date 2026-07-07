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

# Bake in the full-head (non-skull-stripped) MNI152 2009 template used as the
# MNI-space QC report background, so it doesn't get re-downloaded every run.
RUN /usr/bin/python3 -c "from nilearn import datasets; datasets.fetch_icbm152_2009()"

ENTRYPOINT ["mrsiprep-entrypoint"]
