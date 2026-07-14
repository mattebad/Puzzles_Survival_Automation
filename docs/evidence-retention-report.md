# Evidence retention report

Audit `24b21382a0eaac371b13`; generated 2026-07-14T06:16:22.773755+00:00. The JSON detail is local output at `artifacts/evidence-audit.json` and is intentionally not stored under `evidence/`.

This report is a dry-run inventory. No evidence was moved or deleted by the audit.

## Current footprint

| Git state | Files | Bytes |
|---|---:|---:|
| tracked | 1511 | 425,828,236 |
| untracked | 2253 | 1,447,595,565 |
| ignored | 896 | 14,680,064 |
| unknown | 0 | 0 |
| **evidence total** | 4660 | 1,888,103,865 |

Estimated safe duplicate-compaction recovery: **1,278,502,180 bytes**. Git history savings without a history rewrite: **0 bytes**.

## Retention totals

| Retention class | Files | Bytes | Candidate recovery |
|---|---:|---:|---:|
| `PORTABLE_TEST_FIXTURE` | 6 | 4,296,919 | 0 |
| `RUNTIME_TEMPLATE` | 303 | 67,365,613 | 0 |
| `UNRESOLVED_ACTION_EVIDENCE` | 881 | 396,580,102 | 0 |
| `JOURNAL_SOURCE` | 1341 | 40,542,512 | 0 |
| `RECONCILED_JOURNAL` | 38 | 12,148,607 | 0 |
| `REFERENCED_SUPPORTING_EVIDENCE` | 330 | 88,667,932 | 0 |
| `EXACT_DUPLICATE` | 381 | 1,398,884 | 1,398,884 |
| `REPEATED_IDENTICAL_FRAME` | 1380 | 1,277,103,296 | 1,277,103,296 |

## Largest files

| Bytes | Git state | Retention | Path |
|---:|---|---|---|
| 2,281,234 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-daily-claim-evidence-019/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-praise-resume-017-no-input/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-praise-success-018/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-rankings-corrected-015/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-route-recovery-013/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-route-recovery-014/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-phase-e-inventory/live-current-001/close-help-webview-1-attempt-1-post-015.png` |
| 2,280,642 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-route-recovery-013/home-to-more-attempt-1-immediate-before-1-003.png` |
| 2,280,409 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-daily-claim-evidence-019/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-praise-resume-017-no-input/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-praise-success-018/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-rankings-corrected-015/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-route-recovery-014/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,409 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-phase-e-inventory/live-current-001/close-help-webview-1-1-attempt-1-post-019.png` |
| 2,280,303 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-017.png` |
| 2,280,303 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260713-personal-might-praise/live-daily-claim-evidence-019/close-help-webview-1-1-attempt-1-post-017.png` |

## Largest duplicate groups

| Recoverable bytes | Files | Total bytes | Canonical path | SHA-256 |
|---:|---:|---:|---|---|
| 87,496,960 | 137 | 88,140,320 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-immediate-before-1-014.png` | `f07d85477165b4080eeaf19e408d5d7ff40840e527d05690d0816f6e648ea7a8` |
| 56,589,720 | 89 | 57,232,785 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-2-post-017.png` | `3eb1744d266479aef7b5e1a194198652796b57bf441d78158bdedc3e64af3769` |
| 50,553,732 | 165 | 52,461,420 | `evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006-complete/reset-popup-close-post-004.png` | `c863ba9fedda317191cfcb03af5c191d3f18f2b318d2827bdb1f2280f59e85bf` |
| 40,061,952 | 203 | 64,544,256 | `evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/help-all-semantic-fix-20260713/remote/alliance-help-1783986842-immediate-before-1.png` | `ad644936e26a9268e95c35f6a4c3f817d223f5ea5564f3182b2c4d84669ef38b` |
| 34,995,618 | 180 | 49,993,740 | `evidence/sessions/20260713-personal-might-praise/live-attempt-001/home-to-more-source-001.png` | `73952c7f000dcefcf0fd5c7fe3f47be99eb8037e414fea67d1b116153cb1025e` |
| 34,156,695 | 16 | 36,433,808 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-source-007.png` | `7cbc00a77c4f1b7d39108c8c6b3208ad3a3129dac913589da7fd40fd466edc6c` |
| 34,130,595 | 16 | 36,405,968 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/normalize-alliance-to-home-attempt-1-post-006.png` | `1ffbada9c14dee23b868236d0bc29450754c7f76297cdf5dbfc82507a1d2f396` |
| 34,124,955 | 16 | 36,399,952 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/normalize-alliance-to-home-attempt-1-post-005.png` | `542e5c50f9a2dc588c5ba850252dd6a944646b80f43872a28c36bbffccb236c4` |
| 34,120,500 | 16 | 36,395,200 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-immediate-before-1-008.png` | `2f2ceebac1277fce99a2d9bce96b2d11f1cac4fb1036261930b5cf16161d2bf6` |
| 34,012,395 | 16 | 36,279,888 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/normalize-alliance-to-home-attempt-1-post-004.png` | `b119c1a438c45b023c4790a6ced1a692883807d919b16185ef5ceaca76bbefa3` |
| 33,970,695 | 16 | 36,235,408 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-post-009.png` | `d287aaa0f701bc3e3fc2388a645a4b8eaae6fb45e3f0ea88e30e8d9e17a4efa9` |
| 33,969,015 | 16 | 36,233,616 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-2-source-014.png` | `aa0d0b725678f83b602824b8cab0675e2c806dd8e8c63088c7618228aab6a598` |
| 33,951,765 | 16 | 36,215,216 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-post-010.png` | `9d49edd1bb0bf568afcea3fa5ca120473a2bda0b6ce588d4fb47b0e3d7c58811` |
| 33,938,010 | 16 | 36,200,544 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-2-immediate-before-1-015.png` | `fb1fd4dccd52a011b7fd9f9c014419b2e125a1c56a5d636b61a7c548af0fdb9f` |
| 33,924,510 | 16 | 36,186,144 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-1-immediate-before-1-013.png` | `709da5207fd4a272b8a3c1f657b35f908072d8f5033a9f50a357287afcdb0f0c` |
| 33,910,710 | 16 | 36,171,424 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-1-source-012.png` | `c5a35e387e7d27f2b977b830802663b90452445d66f155ec7013d43f3fae3d5e` |
| 33,904,365 | 16 | 36,164,656 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-post-011.png` | `bebd826a5dc8cbb039863eb7d3c8bcc3b8d4986bb753a58f0a9ff1bc42e01543` |
| 25,994,094 | 50 | 30,945,350 | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/personal-might-check-attempt-1-post-004.png` | `9e21a14fefd67167d8237801e570ec442948d908e3718834c5fa71f5dd572a8b` |
| 24,747,120 | 48 | 29,696,544 | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/personal-might-check-attempt-1-immediate-before-1-003.png` | `8a60761c0bd0e0bd3553b03c51327eb22652bc2c2cf1bb04b9935262b6af3a86` |
| 22,819,830 | 12 | 24,894,360 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/startup-close-help-webview-attempt-1-post-005.png` | `e6565bf5d60c2d5537a574d9315c69e3246841db7ac437812ded7e77f57db680` |

## Git history

Reachable evidence blobs: 1001 totaling 291,331,222 bytes.
Current `.git` directory: 433,024,937 bytes; object database: 432,715,996 bytes.
Potential history-only evidence blob upper bound: 447,731 bytes.
No history rewrite, reflog expiration, repack, or destructive cleanup was performed.

## Operating rule

Use `python3 scripts/evidence_hygiene.py plan` for a dry-run candidate list. Use `archive --archive-root <external-path> --execute` only after reviewing the manifest; the tool verifies every content-addressed blob before removing an untracked or ignored duplicate. Tracked, referenced, fixture, runtime-template, decisive, unresolved, and journal artifacts remain protected.

Policy: [`docs/evidence-retention-policy.md`](evidence-retention-policy.md).
