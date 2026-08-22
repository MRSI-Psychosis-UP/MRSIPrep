# Contributing to MRSIPrep

Thanks for considering a contribution. MRSIPrep is a BIDS App for
already-quantified whole-brain MRSI derivatives, built along the lines the
[NiPreps](https://www.nipreps.org/) community established for MRI
preprocessing: a containerized, version-pinned dependency stack, an
independently cacheable node per processing stage, a visual per-recording
report, and machine-readable provenance for every run.

Two documents sit alongside this one and are worth reading before a first
change:

- [`docs/architecture.md`](docs/architecture.md) — how the pipeline is laid out
  and which package owns what.
- [`docs/extending.md`](docs/extending.md) — worked recipes for the common
  extensions (a new nucleus, a new tissue or registration backend).

## Development setup

MRSIPrep's processing stages shell out to ANTs, FSL, FreeSurfer, PETPVC and
Chimera, so the practical way to develop is inside the container, which already
has them:

```bash
# Thin test image: the published image plus pytest.
cat > /tmp/Dockerfile.test <<'EOF'
FROM mrsiup/mrsiprep:cpu
RUN /usr/bin/python3 -m pip install --no-cache-dir pytest pytest-cov
ENTRYPOINT []
EOF
docker build -f /tmp/Dockerfile.test -t mrsiprep-test:local /tmp

# Run the suite against your working tree (mounted, not copied).
docker run --rm -v "$PWD":/src -w /src mrsiprep-test:local \
  /usr/bin/python3 -m pytest -q
```

Mounting the source means you edit locally and re-run immediately; no rebuild
is needed for Python changes. To rebuild the app image itself after changing
source, `docker/update_mrsiprep_image.sh` relayers just the MRSIPrep package on
top of the existing dependency image rather than rebuilding FSL/FreeSurfer.

A plain local `pip install -e ".[dev]"` also works for the many modules that
don't touch external binaries, but expect skips/failures in the interface tests.

## Tests

```bash
docker run --rm -v "$PWD":/src -w /src mrsiprep-test:local \
  /usr/bin/python3 -m pytest -q --cov=mrsiprep --cov-branch
```

- **`tests/` is gitignored.** New test files need `git add -f`. This trips up
  most first contributions.
- Branch coverage is currently ~90%; CI reports it to Codecov on every PR.
  New code should come with tests, and please don't regress the total.
- One test, `test_raises_with_informative_message_when_not_found_anywhere`,
  fails *inside the container* because `/opt/freesurfer` genuinely exists
  there while the test asserts the not-found path. It passes on CI's clean
  runner. That single failure is expected locally.

### What a good test looks like here

Prefer tests that pin behaviour which would otherwise fail *silently*. The
suite leans on this deliberately — e.g. that a parcellation is resampled with
nearest-label rather than linear interpolation (linear would invent label
values), or that an all-zero weight vector doesn't divide by zero. Asserting a
file merely exists catches much less.

## Style

- Match the surrounding code; there's no enforced formatter.
- Public functions carry Sphinx-style docstrings (`:param:`/`:returns:`/
  `:raises:`). `docs/api.md` is generated from them.
- **Comment the "why", not the "what."** The codebase's comments are mostly
  about non-obvious constraints — why Chimera is forced to `--nthreads 1`, why
  T1 lookup refuses metabolite aliasing. Those are the ones worth writing.
- **Refuse to guess.** Where a value can't be determined, raise an error naming
  the file or flag that would supply it, rather than substituting a plausible
  default. `resolve_metabolite_t1()` in `mrsiprep/mrsi/t1_correction.py` is the
  reference example.

## Pull requests

CI runs tests, CodeQL, Codecov, and Codacy static analysis; all must pass.

- Codacy fails a PR on **any** new issue. It runs Opengrep/semgrep, which
  occasionally false-positives — e.g. constructing a `subprocess.CompletedProcess`
  in a test double is flagged as command injection. Suppress those the way
  `tests/test_subprocess_utils_units.py` does (`# nosec` on the import,
  `# nosemgrep` at the call), with a comment explaining why it's safe.
- Describe the *why* in the PR body. Several recent PRs document a subtle bug
  the change fixes; that context is what makes review possible.
- Note any change to output paths or file naming explicitly — downstream users
  depend on the derivative layout.

## Reporting bugs

Please include the MRSIPrep version, the exact command, and the relevant part
of the run's `provenance.json` (it records the resolved config and the external
tool versions). For processing problems, the per-recording HTML report is
usually more informative than the console log.
