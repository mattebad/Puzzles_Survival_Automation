# Evidence retention report

Audit `2f98690415fec98fec16`; generated 2026-07-15T00:25:38.044421+00:00. The JSON detail is local output at `artifacts/evidence-audit.json` and is intentionally not stored under `evidence/`.

This report is a dry-run inventory. No evidence was moved or deleted by the audit.

## Current footprint

| Git state | Files | Bytes |
|---|---:|---:|
| tracked | 1515 | 425,847,314 |
| untracked | 4107 | 4,619,212,471 |
| ignored | 36 | 0 |
| unknown | 0 | 0 |
| **evidence total** | 5658 | 5,045,059,785 |

Estimated safe duplicate-compaction recovery: **2,135,439,936 bytes**. Git history savings without a history rewrite: **0 bytes**.

## Retention totals

| Retention class | Files | Bytes | Candidate recovery |
|---|---:|---:|---:|
| `PORTABLE_TEST_FIXTURE` | 6 | 4,296,919 | 0 |
| `RUNTIME_TEMPLATE` | 303 | 67,365,613 | 0 |
| `UNRESOLVED_ACTION_EVIDENCE` | 1031 | 491,673,542 | 0 |
| `JOURNAL_SOURCE` | 1027 | 58,728,752 | 0 |
| `RECONCILED_JOURNAL` | 50 | 16,370,711 | 0 |
| `REFERENCED_SUPPORTING_EVIDENCE` | 335 | 2,271,184,312 | 0 |
| `EXACT_DUPLICATE` | 656 | 3,367,923 | 3,367,923 |
| `REPEATED_IDENTICAL_FRAME` | 2250 | 2,132,072,013 | 2,132,072,013 |

## Largest files

| Bytes | Git state | Retention | Path |
|---:|---|---|---|
| 524,288,000 | untracked | `REFERENCED_SUPPORTING_EVIDENCE` | `evidence/sessions/20260714-daily-flow-acquisition.zip.001` |
| 524,288,000 | untracked | `REFERENCED_SUPPORTING_EVIDENCE` | `evidence/sessions/20260714-daily-flow-acquisition.zip.002` |
| 524,288,000 | untracked | `REFERENCED_SUPPORTING_EVIDENCE` | `evidence/sessions/20260714-daily-flow-acquisition.zip.003` |
| 524,288,000 | untracked | `REFERENCED_SUPPORTING_EVIDENCE` | `evidence/sessions/20260714-daily-flow-acquisition.zip.004` |
| 85,364,380 | untracked | `REFERENCED_SUPPORTING_EVIDENCE` | `evidence/sessions/20260714-daily-flow-acquisition.zip.005` |
| 2,281,234 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-pre-dispatch-1784059560/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-pre-dispatch-1784059800/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-back-attempt-1784059287/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-bioenhancer-navigation-success/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-bioenhancer-retry-source/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-current/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-recovered-daily/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-supply-source-2/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-supply-source-3/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/remote-supply-source/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/supply-depot-route-20260714-152435/close-help-webview-1-attempt-1-post-015.png` |
| 2,281,234 | untracked | `REPEATED_IDENTICAL_FRAME` | `evidence/sessions/20260714-daily-flow-acquisition/supply-depot-route-20260714-152435/evidence/close-help-webview-1-attempt-1-post-015.png` |
| 2,280,642 | untracked | `UNRESOLVED_ACTION_EVIDENCE` | `evidence/sessions/20260713-personal-might-praise/live-route-recovery-013/home-to-more-attempt-1-immediate-before-1-003.png` |

## Largest duplicate groups

| Recoverable bytes | Files | Total bytes | Canonical path | SHA-256 |
|---:|---:|---:|---|---|
| 117,091,520 | 183 | 117,734,880 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-immediate-before-1-014.png` | `f07d85477165b4080eeaf19e408d5d7ff40840e527d05690d0816f6e648ea7a8` |
| 72,412,119 | 125 | 77,363,375 | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/personal-might-check-attempt-1-post-004.png` | `9e21a14fefd67167d8237801e570ec442948d908e3718834c5fa71f5dd572a8b` |
| 56,299,698 | 99 | 61,249,122 | `evidence/sessions/20260713-personal-might-praise/live-personal-might-leaderboard-016/personal-might-check-attempt-1-immediate-before-1-003.png` | `8a60761c0bd0e0bd3553b03c51327eb22652bc2c2cf1bb04b9935262b6af3a86` |
| 50,159,070 | 79 | 50,802,135 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/more-to-rankings-attempt-2-post-017.png` | `3eb1744d266479aef7b5e1a194198652796b57bf441d78158bdedc3e64af3769` |
| 40,149,265 | 66 | 40,766,946 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/personal-might-back-to-rankings-attempt-1-post-009.png` | `803eb874857de8380bcd87ed9f41036d54c2bccc3bb99623aa96c53c58748150` |
| 37,199,916 | 123 | 39,107,604 | `evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006-complete/reset-popup-close-post-004.png` | `c863ba9fedda317191cfcb03af5c191d3f18f2b318d2827bdb1f2280f59e85bf` |
| 32,088,368 | 53 | 32,705,452 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/personal-might-back-to-rankings-attempt-1-immediate-before-1-008.png` | `cd2da83f3620850768f61586904dc3b1f810f0389a0a5e489eb433506958adb5` |
| 29,656,042 | 14 | 31,937,276 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-attempt-1-post-015.png` | `6a1b605702901de9b9f48478acab07d0f556928e6fdd19fa8decaad5bca441c4` |
| 29,645,317 | 14 | 31,925,726 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-019.png` | `790f1cdc6692846bd43949abe1a448ee962b9b563ded625a0058bda42a735c17` |
| 29,643,939 | 14 | 31,924,242 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-017.png` | `39f5663ee70953301b6e433cd5aab871858741e7cfedf8d78decfb25473c7a40` |
| 29,639,233 | 14 | 31,919,174 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-quest-attempt-1-immediate-before-1-018.png` | `6ba7728ca29802360dc46ba0be1c61fbc1dd67ca63ebb9f9a92044260164f34a` |
| 29,636,230 | 14 | 31,915,940 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-attempt-1-post-017.png` | `23aff171f096cd51744f88680836dad62ccafc971c46dbeb8468dd6831eb472d` |
| 29,628,911 | 14 | 31,908,058 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-quest-attempt-1-source-017.png` | `d9a938ac12b2d5e783283ae2dba6993b80eee46bdc34227a2da4dd3b14375e80` |
| 29,626,233 | 14 | 31,905,174 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-attempt-1-post-016.png` | `040c5a0f93d8e84076148aee3e43400154b728d45d59b80eb5a6838e8dcf3395` |
| 29,623,854 | 14 | 31,902,612 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-021.png` | `d09e59e9a77e81f29c3ba426dc4fe6179b022abe77a1b18e46527d4ce1ae9d86` |
| 29,621,098 | 14 | 31,899,644 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-016.png` | `35e37fa7dd345dc4a3d301facb6b5ebfc9e288dc0060ce6e2368066c12190b04` |
| 29,619,083 | 14 | 31,897,474 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/rankings-back-to-home-attempt-1-post-016.png` | `3091aea4104769388824c84b4d8d75c21ee073164507d533bc75b27c97ab87d6` |
| 29,617,783 | 14 | 31,896,074 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/close-help-webview-1-1-attempt-1-post-020.png` | `df61662961e4c37248342ef5b2cdf554b13163d0e125ea2385dfb0e4aaeb6346` |
| 29,615,196 | 14 | 31,893,288 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/rankings-back-to-home-attempt-1-post-015.png` | `5b7172ae65b11707281510e988a843cd57446e6f5cb36f2a363b2fb66182b9ee` |
| 29,602,469 | 14 | 31,879,582 | `evidence/sessions/20260713-personal-might-praise/live-claim-success-020/home-to-more-attempt-1-source-007.png` | `7cbc00a77c4f1b7d39108c8c6b3208ad3a3129dac913589da7fd40fd466edc6c` |

## Git history

Reachable evidence blob size was not measured.
Current `.git` size was not measured.
Potential history-only evidence blob size was not measured.
No history rewrite, reflog expiration, repack, or destructive cleanup was performed.

## Operating rule

Use `python3 scripts/evidence_hygiene.py plan` for a dry-run candidate list. Use `archive --archive-root <external-path> --execute` only after reviewing the manifest; the tool verifies every content-addressed blob before removing an untracked or ignored duplicate. Tracked, referenced, fixture, runtime-template, decisive, unresolved, and journal artifacts remain protected.

Policy: [`docs/evidence-retention-policy.md`](evidence-retention-policy.md).
