# BlueStacks acceptance, November 2 UTC

PR [#16](https://github.com/mattebad/Puzzles_Survival_Automation/pull/16)
remains draft and unmerged. Permanent scheduling is disabled. This report
supplements the [November 1 report](bluestacks-route-status-20261101.md);
historical receipts retain their original source scope.

The real reset test entered Campaign stages at 23:57:29, 23:58:28 and 23:59:23
on November 1, then 00:00:23, 00:01:20, 00:02:07, 00:03:01 and 00:03:53 on
November 2, in one continuing game client and drain. Eight wins consumed 112 AP
with 48 inputs; 120 + 1 regenerated - 112 = 9 AP, then Home. The whole drain
scheduled completion +300 seconds. This proves consuming entries on both sides
of actual midnight; it is not merely a battle held open across reset. The
controller stopped later at a zero-Hold Supply recognition failure, so it does
not prove a complete two-hour cohort. Audit:
`.local-orchestrator/logs/real-reset-crossing-supply-navigation-stop-audit-20261102T0023Z.json`.

Supply's two retained zero-Hold failures identified real OCR and circle-proposal
defects. A tight caption fallback retains the complete Claim label and all
button/HUD checks. A fallback circle proposal is used only when the original
proposal is absent, with tighter glyph centering and unchanged final edge
support, safe interior and HUD exclusions. The fresh full route then passed:
Home → Depot → one Hold, free attempts 9→0 → Home, four inputs. Its audit checks
431 unchanged source files, 19 PNGs and 17 capture references. All 47 focused
Supply checks subsequently passed:
`.local-orchestrator/logs/supply-fresh-full-home-caption-circle-live-audit-20261102T0058Z.json`.

Tavern initially skipped a real enabled purple Free Recruit 1x because the
native Daily free attempts counter displayed zero. The user clarified that the
enabled free control governs eligibility. The fix preserves the native counter
as observed, does not infer five consumed actions from zero, and records one
use only after the recruit result and cooldown transition. Confirmed daily
ownership, unknown-result stops and independent Intermediate/Advanced deadlines
remain enforced. All 107 focused Tavern tests passed.

Live acceptance at 01:26–01:30 UTC used six inputs and one Basic free recruit
from that exact zero-counter state, verified the result and Free in 00:09:48,
and returned Home. Tickets stayed 91→91; persisted Basic count became one.
Intermediate deadline 1793594260.4039137 and Advanced deadline
1793672002.075106 stayed unchanged. No game restart or quota rearm occurred.
Independent replay checked the source, result, cooldown and Home, 434 unchanged
source files, 20 PNGs and 17 capture references. All nine flow/service controls
were OFF, with released owners and no unresolved effect:
`.local-orchestrator/logs/tavern-enabled-free-stale-zero-live-final-audit-20261102.json`.

The earlier post-reset cohort also verified Nova one Praise/Home, Bioenhancer
one Free Research/Home, Campaign one later win/Home and Ultimate one Flee/Home.
The user paused Enhancement after five navigation inputs and zero Confirms.
Its two-input Home recovery preserved all three reservations and consumed no
material. That interrupted run is not uninterrupted Enhancement acceptance.
Current-day uninterrupted Enhancement, Personal Might, final source/cadence
reconciliation and current-head Windows/Linux CI remain outstanding. Earlier
manual Enhancement/Ultimate passes and restart/cadence receipts retain their
documented source scope. Defeat/Continue remains offline-proven only.
