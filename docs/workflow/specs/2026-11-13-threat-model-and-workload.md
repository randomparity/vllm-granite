# Threat model and workload (#3)

## Problem
Issue #3 needs a bounded threat model and workload before baseline execution.

## Scope
One documentation unit: `docs/threat-model-and-workload.md` plus a README link.
Authority: issue #3, epic #1, and approved scope q3-9a4b55c3.
Reuse `docs/compatibility.md` limits and comparison protocol without changing them.
Describe local rootless serving, a compromised inference process, assets, allowed
access and residual GPU-driver/ioctl exposure. Define fixture IDs and bounded
cold/warm startup, chat, concurrency/context, invalid input, cancellation,
stop/restart and safe resource-error recovery cases with outcomes and cleanup.
Keep Fedora 44/x86_64, one A6000, Granite 4.2 8B, loopback and SELinux enforcing.
Pins/budgets remain #2; launch/acquisition/privileges #4; executable proof #5;
tracing #6; syscall review #7; policy/enforcement #8/#9; comparison execution
#10; operational guide #11. No harness, downloads, deployment or GPU execution.
No ownership migration: README is the only existing navigation entry point.

### Design
A linked document separates intended containment from proven enforcement.
It lists assets and permitted device/filesystem/network use, offline serving,
trusted acquisition versus hostile requests, and residual kernel/driver risk.
A scenario table supplies stable fixture IDs, requests, expected results and
per-case cleanup, inheriting numerical bounds from #2. Select plain chat without
repository plugins or custom parsers; downstream execution freezes exact payloads
and template-aware token counts. No exploit, destructive OOM or GPU stress case.

### Failure model
Inside: a local maintainer follows the future workload on the declared target.
Ambiguous fixtures, unbounded failure injection, unsafe access assumptions or
false security claims could misdirect downstream implementation. Require bounded
fixtures, stop conditions and private evidence; unmet containment blocks execution.
Accepted: this phase defines expectations; #4/#5 prove feasibility and behavior,
#8/#9 prove policy enforcement. No claim of GPU-driver exploit prevention.
Outside: remote serving, malicious host operators, kernel compromise prevention,
training, other GPUs/architectures and distributed serving.

## Success
Every issue criterion has a scenario or threat-model entry; outcomes and cleanup
are bounded; limits agree with #2; public text contains no private identifiers.
README navigation resolves and independent review has no unresolved blockers.

## Validation
- Threat/access/scenario definitions: Mode: task-test-not-applicable.
  Human-readable expectations have no executable consumer. Wording assertions
  cannot prove containment or future inference behavior; inspect requirements,
  source claims, limits, scenario outcomes and cleanup directly.
- README navigation: Mode: focused-test. Parse README Markdown targets; require
  the new threat-model target and resolve local destinations. Missing link or file
  raises AssertionError. Run this self-contained green command from repo root:
  ```sh
  python3 -c 'import re; from pathlib import Path; links=re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", Path("README.md").read_text()); assert "docs/threat-model-and-workload.md" in links; assert all(Path(t).is_file() for t in links if "://" not in t)'
  ```
- Formatting: `git diff --check` must exit 0; inspect public text for identifiers.
  No repository CI, guardrails or hooks exist; no infrastructure tests apply.
