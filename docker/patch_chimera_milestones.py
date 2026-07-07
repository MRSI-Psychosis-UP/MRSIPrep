"""Inject coarse progress milestones into the installed chimera package.

chimera's own CLI prints almost nothing between startup and completion for a
single subject/scheme run (10-20+ minutes of silence is normal), which reads
as a hang. This patches the installed chimera/chimera.py to print a milestone
line at the start of each supra-region's processing and at the start of
cortical parcellation fusion, gated on the CHIMERA_MILESTONES env var so it
stays silent unless mrsiprep's wrapper opts in (verbose >= 2).

Idempotent: running this twice is a no-op the second time.
"""

from __future__ import annotations

import importlib.util
import sys

MARKER = "# mrsiprep-milestone-patch"

SUPRA_LOOP_ANCHOR = "            files2del = []  # Temporal files that will be deleted\n            exec_cmds = []\n            for supra in gm_sub_names:\n"
SUPRA_LOOP_PATCH = (
    "            files2del = []  # Temporal files that will be deleted\n"
    "            exec_cmds = []\n"
    "            for supra in gm_sub_names:\n"
    f'                {MARKER}\n'
    "                if os.environ.get(\"CHIMERA_MILESTONES\"):\n"
    "                    print(f\"[chimera-milestone] processing supra-region: {supra}\", flush=True)\n"
)

CORTICAL_ANCHOR = '            if bool_ctx:\n\n                # Atributes for the cortical parcellation\n                atlas_names = self.parc_dict["Cortical"]["parcels"]\n\n                proc_dict = self.parc_dict["Cortical"]["processing"]\n                ctx_meth = proc_dict["method"]\n'
CORTICAL_PATCH = (
    "            if bool_ctx:\n"
    f'                {MARKER}\n'
    "                if os.environ.get(\"CHIMERA_MILESTONES\"):\n"
    '                    print("[chimera-milestone] starting cortical parcellation fusion", flush=True)\n'
    "\n"
    "                # Atributes for the cortical parcellation\n"
    '                atlas_names = self.parc_dict["Cortical"]["parcels"]\n'
    "\n"
    '                proc_dict = self.parc_dict["Cortical"]["processing"]\n'
    "                ctx_meth = proc_dict[\"method\"]\n"
)


def main() -> int:
    spec = importlib.util.find_spec("chimera.chimera")
    if spec is None or spec.origin is None:
        print("chimera.chimera module not found; nothing to patch.", file=sys.stderr)
        return 1
    target = spec.origin
    text = open(target, encoding="utf-8").read()

    if MARKER in text:
        print(f"{target} already patched; skipping.")
        return 0

    if SUPRA_LOOP_ANCHOR not in text:
        print(f"Supra-region loop anchor not found in {target}; chimera version may have changed. Skipping that patch.", file=sys.stderr)
    else:
        text = text.replace(SUPRA_LOOP_ANCHOR, SUPRA_LOOP_PATCH, 1)

    if CORTICAL_ANCHOR not in text:
        print(f"Cortical fusion anchor not found in {target}; chimera version may have changed. Skipping that patch.", file=sys.stderr)
    else:
        text = text.replace(CORTICAL_ANCHOR, CORTICAL_PATCH, 1)

    if MARKER not in text:
        print("No anchors matched; chimera.py left unmodified.", file=sys.stderr)
        return 1

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"Patched {target} with milestone prints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
