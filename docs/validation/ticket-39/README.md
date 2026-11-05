# Issue #39: static debt ratchets

Implemented and offline-proven; not live acceptance. No runtime behavior, device
access, deployment, registration or scheduling changes are part of this work.

## Introduced baseline

The pre-change source is `0c58b58` (the verified issue #47 tree), with the tool
configuration introduced by this change. Independent Windows Python 3.12.10 and
Linux Python 3.11.18 scans produce identical file inventories and exact
per-file/per-code counts, not merely equal totals.

| Pinned analyzer | Windows findings | Linux findings | Files with findings |
| --- | ---: | ---: | ---: |
| Ruff 0.17.3 | 257 | 257 | 85 |
| Vulture 2.16 | 457 | 457 | 134 |
| mypy 2.4.1 | 376 | 376 | 25 |

The initial inventory contains 438 active `.py` files. The checker and its test
module bring that to 440 without adding findings. Ruff E4/E7/E9/F covers active
Python sources; Vulture scans that exact inventory at confidence 60, including
unused functions/classes. Ruff's normal exclusions and Git ignores apply, plus
the explicit historical/data/vendor exclusions in `pyproject.toml`. Existing
heuristic Vulture findings are debt, not permission to delete dynamically used
interfaces. Count budgets cannot distinguish a replaced diagnostic with the same
file/code/count; they are not proof that all code is defect-free.

## Maintenance and enforcement

Install `requirements-dev.txt`, then run:

```console
python -B scripts/check_static.py
python -B scripts/check_static.py --refresh-baseline
```

The second command only records reductions. New files/rules have zero allowance;
a reduction requires a committed tighter baseline instead of retaining spare
capacity. CI runs on shard zero of both OSes, before a successful execution
receipt can be uploaded. It also compares the committed budget with the PR base
(or previous push revision), so increasing the JSON allowance cannot hide new
findings. A missing baseline is allowed only when it is actually absent at that
valid base revision; unavailable history and analyzer/parse failures fail closed.
Tool-version mismatches fail instead of silently changing the measurement.

Actual CLI probes reject a new undefined name (`F821`), an unused function
(`function:60`), and a new safety-package return-type error (`return-value`). A
stale type allowance fails until refresh lowers it. Three focused regression
methods cover new dimensions, removed debt files, and unchanged totals that
attempt to transfer debt to another file or analyzer. Complete discovery assigns
the new test module automatically; no test allowlist or skip is added.

## Hosted timing correction

[The first hosted attempt](https://github.com/mattebad/Puzzles_Survival_Automation/actions/runs/41953493819)
passed both static gates and complete Linux discovery. Windows failed the existing
`test_expensive_planner_runs_once_and_transport_uses_actual_new_capture`: no
swipe reached its fake backend. The original inner rejection reason was not
retained. A controlled 101ms post-capture overrun reproduces that exact assertion
via the unchanged 100ms freshness guard, demonstrating a wall-clock dependency.

The planner-delay and validation-expiry scenarios now reuse the existing test
`Clock`, with the same 150ms logical delays and 100ms frame limit. Every original
assertion stays; exact maximum-step/stale-source reasons and an explicit expiry
assertion make the cases stricter. All 20 affected cases pass with process
launches blocked. A throwaway mutation that disables only the age guard fails
the expiry test and produces one forbidden swipe in the fake backend. No
production timeout or runtime behavior changes, and no test ID is removed.

## Explicit shrinking type-debt list

All 35 Python files in `safe_action_core/` and `automation_service/` are analyzed.
The configuration checks untyped bodies, requires function annotations, rejects
implicit optional arguments, and warns on returned `Any` and unused ignores;
imported implementation files outside these two roots are followed silently.
There is no `ignore_errors`, omitted safety module, or blanket missing-import
suppression. The ten currently clean files and every new file must have zero
errors. The 25 files below are exceptions from the **zero-error condition**, not
from analysis: each existing error code has its own non-increasing allowance in
`.github/static-check-baseline.json`. Fixes must reduce that allowance; a clean
file must leave the exception list. The 376 existing type errors are not reported
as a clean mypy run.

| Explicit debt file | Errors | Existing diagnostic reasons and counts |
| --- | ---: | --- |
| `automation_service/actions.py` | 13 | `assignment` (3), `no-any-return` (6), `no-redef` (1), `union-attr` (3) |
| `automation_service/bioenhancer.py` | 23 | `arg-type` (2), `assignment` (1), `no-any-return` (1), `no-untyped-def` (18), `var-annotated` (1) |
| `automation_service/campaign.py` | 40 | `arg-type` (7), `index` (4), `no-any-return` (1), `no-untyped-def` (24), `operator` (1), `union-attr` (1), `var-annotated` (2) |
| `automation_service/cli.py` | 9 | `arg-type` (2), `dict-item` (2), `no-any-return` (1), `no-untyped-def` (1), `union-attr` (3) |
| `automation_service/enhancement.py` | 22 | `arg-type` (2), `no-untyped-def` (20) |
| `automation_service/nova.py` | 9 | `arg-type` (1), `no-any-return` (2), `no-untyped-def` (5), `operator` (1) |
| `automation_service/overlays.py` | 5 | `arg-type` (1), `index` (1), `return-value` (1), `union-attr` (2) |
| `automation_service/personal_might.py` | 30 | `assignment` (2), `attr-defined` (1), `call-overload` (4), `index` (1), `no-untyped-def` (20), `operator` (1), `union-attr` (1) |
| `automation_service/recruitment.py` | 9 | `arg-type` (1), `no-any-return` (1), `no-untyped-def` (7) |
| `automation_service/registry.py` | 8 | `arg-type` (8) |
| `automation_service/scheduler.py` | 50 | `arg-type` (22), `assignment` (9), `call-arg` (6), `no-any-return` (2), `union-attr` (11) |
| `automation_service/screens.py` | 7 | `assignment` (5), `operator` (1), `type-var` (1) |
| `automation_service/service.py` | 40 | `arg-type` (4), `assignment` (2), `attr-defined` (1), `no-untyped-def` (20), `union-attr` (10), `var-annotated` (3) |
| `automation_service/session.py` | 1 | `call-arg` (1) |
| `automation_service/state.py` | 12 | `arg-type` (9), `assignment` (1), `call-overload` (1), `operator` (1) |
| `automation_service/supply.py` | 25 | `arg-type` (3), `assignment` (1), `no-untyped-def` (16), `return-value` (2), `union-attr` (3) |
| `automation_service/temporal.py` | 1 | `assignment` (1) |
| `automation_service/ultimate.py` | 36 | `arg-type` (4), `assignment` (1), `call-overload` (1), `index` (1), `no-untyped-def` (29) |
| `safe_action_core/executor.py` | 2 | `arg-type` (1), `assignment` (1) |
| `safe_action_core/models.py` | 3 | `arg-type` (1), `attr-defined` (1), `no-any-return` (1) |
| `safe_action_core/path_safety.py` | 2 | `no-untyped-def` (2) |
| `safe_action_core/policy.py` | 4 | `arg-type` (2), `no-untyped-def` (1), `var-annotated` (1) |
| `safe_action_core/resource_effect_authority.py` | 19 | `arg-type` (19) |
| `safe_action_core/scheduler_invocation_state.py` | 2 | `no-any-return` (1), `union-attr` (1) |
| `safe_action_core/store.py` | 4 | `arg-type` (1), `assignment` (1), `return-value` (2) |

This ticket does not implement import-direction rules; those remain issue #22.
Revision-bound hosted Windows/Linux results belong in the PR/issue report, not a
claim of native gameplay readiness.
