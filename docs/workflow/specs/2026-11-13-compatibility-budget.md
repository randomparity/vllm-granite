# Compatibility and budget record (#2)

## Problem
Issue #2 needs an evidence-backed baseline proposal before acquisition or measurement.

## Scope
Implement one documentation unit: `docs/compatibility.md` and its README link.
Source: issue #2, epic #1, and approved charter q2-a3b8a786.
Record host inventory, upstream artifact candidates, dtype/backend rationale,
initial resource budgets, and a comparison protocol declared before measurements.
Keep observations, upstream support, proposals, and measured results distinct.
No implementation exists to move; README is the only affected entry point.
No ADR is needed: this records bounded experimental candidates, not architecture.
Threat/workload definitions belong to #3; provisioning/launch/CDI/rootless proof
to #4; fit/performance proof to #5; tracing/policy/enforcement to #6–9;
full regression and operator guide to #10–11. No downloads, launches or GPU runs.

### Design
One linked document contains a sanitized host matrix with collection methods,
current primary-source evidence and immutable image/model candidates, an
Ampere-compatible precision/backend proposal, numerical context/concurrency and
memory/disk limits, and a bounded baseline/custom comparison method and thresholds.
Conflicting upstream metadata is disclosed; unresolved compatibility stays unproved.
The proposed envelope is a starting gate, not a claim that inference fits or works.

### Failure model
Inside: a maintainer follows this document on Fedora 44/x86_64 with one A6000.
Wrong pins, unsupported assumptions, missing bounds and accidental host identifiers
can misdirect later work. Stop downstream validation on unresolved incompatibility
or unmet budgets; do not widen limits or weaken security to manufacture success.
Accepted: no GPU execution proof in this documentation phase; #4/#5 own it.
Outside: other GPUs, architectures, distributed serving and remote API exposure.

## Validation
- Host/support/pins/budgets/protocol: Mode: task-test-not-applicable.
  These are human-readable experimental decisions without an executable consumer;
  wording assertions cannot prove compatibility. Check primary sources, registry
  metadata, pinned model configuration, inventory output and numerical consistency.
- README navigation: Mode: focused-test. Resolve each local Markdown link to a
  real file; missing destination raises AssertionError (red). README local-link case:
  `python3 /tmp/quest2-q2-a3b8a786/check-links.py` must print success (green).
- Formatting: `git diff --check`; expect exit 0. Scan all public text for private
  identifiers before publication. No repository CI, test suite or hooks exist.

## Success
Every issue-2 field is recorded with status/evidence; image and model are immutable;
initial limits and acceptance thresholds precede measured results. README resolves
its link, guardrails pass, and independent review finds no unresolved blockers.
