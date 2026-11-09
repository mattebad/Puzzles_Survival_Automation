# Current handoff

Updated 2026-11-09. This file is volatile session state.
Current owner direction and planning live in [tracker #53](https://github.com/mattebad/Puzzles_Survival_Automation/issues/53) and its tickets.

## Manual walkthrough correction state (2026-11-09)

- Source: the original workspace's immutable
  `.local-captures/manual-walkthrough-2026-11-09T04-42-35-490Z/walkthrough-report.txt`,
  SHA-256 `61bdd23c6740a54b28931ab4ccf3b0d80dd440bb203fdfb8ba1725c18059725b`.
  Its 261 screenshots/accounting document manual gameplay, not native acceptance.
- Fresh correction branch: `fix/manual-walkthrough-corrections-20261109` in sibling
  `Puzzle_Survival_walkthrough_corrections_20261109`. Original unrelated changes and
  raw evidence are preserved; authorized native results update Original canonical state.
- Latest bounded native visits restored service disabled, scheduler ineligible and
  all 24 flows disabled. The observed reset remains game-day-2026-11-09,
  ending November 10 00:00 UTC.
- Completed manual effects below must not be repeated to manufacture receipts:

| Ticket | Actual November 9 effect |
| --- | --- |
| #54 | Later aggregate batch 5→35 and first 30-point chest; earlier batch 0→5 already complete. |
| #66 | Separate canonical use 129,809→129,808; walkthrough inspection only. |
| #69 | Floor 61 defeat, then eight independent green chests totaling 2,927 medals. |
| #56 | One Help All served three requests; later empty despite gold footer. |
| #77 | Ten ordinary HOT donations, attempts 20→10; quota remains complete despite regeneration. |
| #73 | One 1★ Gear fallback for 1,000 Alliance Coins; no additional Weekly buy due. |
| #72 | Chip x100 and Module x15 bought; revised Mystery Shop entry must not repeat purchases. |
| #70 | Free six-hour Material Production started; observe active/completed slot before maintenance. |
| #71 | Old craft claimed, one 100-part/12-hour Normal Craft started; post-start parts unobserved. |
| #75 | Three free entry/flee cycles, allowance 3→0; passes unchanged. |
| #76 | Queue 1 Troop Load II started with 05:56:53 initial timer. |
| #78 | One Farm-specific item boost; same Farm Boosting 23:59:39. |
| #95 | Specifically approved Training confirmation once, then Training Applied; debit unobserved. |
| #96 | One saved Set 1 dispatch, LOSE/damage result, one reward-row claim and three checks. |
| #67 | Four starts: Fighter/Vehicle current maximum 1,510, Shooter/Rider 250. Old claims are separate. |

- Implementation comparisons preserve working Daily/Food/Ruins, Nano transitions and Farm
  behavior. Corrections address Help readiness without name OCR, capture-bound donation grants,
  exact Timed Recruit Coin currency handling, mapped Mystery Shop entry, Duel defense readback,
  Research active successors, scoped Training confirmation, Hall result and training quantity entry.
- Timed Tavern Coins are prospectively allowlisted as exact UI `Timed Recruit Coin`; current
  currency/price/affordability still apply. No new premium purchase is due this reset, and
  allowlisting/current quote does not supply an independent finite operator spending approval.
- No unrecorded manual effects have been converted into canonical action receipts or counters.
  Inspected supported reconciliation APIs handle existing recorded actions, not this unrecorded
  manual portfolio. Already-completed effects remain excluded this reset; this does
  not block fresh distinct Help requests or Daily reward batches/chests.
  Do not fabricate intents, clear counters or replay completed effects.
- Unknown-cost future talent switches, Economy Apply, Farm premium branch, exact training boxes
  and continuous completion/restart remain evidence gaps. Historical Training approval is not
  standing Reset authority. Controls stay disabled; manual proof and native acceptance remain distinct.

### Canonical live continuation (2026-11-09)

- Current explicit owner authorization was recorded under Original
  `.local-captures/canonical-corrections-live-20261109T073949341591Z/`.
  Corrected source `35805a3` uses Original canonical state from the linked worktree
  and supports bounded `serve --once --max-duration-seconds 180`.
- **#54 passed:** `DAILY_REWARDS_PASS_VERIFIED`; one fresh aggregate Claim,
  points 35→65, then one newly glowing 60-point chest with same-slot Claimed proof.
  All five slots were reobserved: slots 1/2 claimed, 3/4/5 not ready.
  Four total inputs, two confirmed reward actions, verified terminal Home.
  Source/before/transport/after/semantic/Home records are in `daily-rewards/`;
  `daily-rewards-cli.stdout.jsonl` retains the actual canonical result.
  The earlier manual 30-point chest and batches were not repeated.
- **#56 empty path verified, consuming acceptance still evidence_required:**
  canonical Home→Alliance→Help→Speedup Help recognized the exact no-requests message.
  Six navigation inputs, zero Help calls, zero credited requests, verified Home.
  `help-fixed-identity/` and its CLI output retain the actual deferred result.
  Next scenario is a genuinely fresh ready request batch, not the cleared manual batch.
- The first Help invocation used placeholder account/server labels and was rejected
  before gameplay input. Corrected labels come from `resource_fixed_runtime_binding()`.
  The existing CAS-guarded `unblock_flow` removed only that corrected preflight block;
  its failed attempt and failure count were preserved. No retry budget was reset.
- The twelve retained unresolved Core rows are non-consequential zero-cost navigation.
  Existing `SafetyStore.has_action_block()` excludes them; there is no consequential
  unresolved action block. Leave those historical rows unchanged.
- `final-canonical-service-status.json` proves service OFF, scheduler ineligible,
  all 24 controls OFF. No merge, deployment or permanent enablement occurred.
  Other manual effects above are not promoted to canonical acceptance by these visits.

### Offline verification and limits

- Help retained ready/success/empty frames, five-chest loop, exact Food decrement, Ruins,
  donation freshness/regeneration/UNKNOWN and current Duel portrait cases pass focused checks.
  Shop policy, actual Timed Coin quote and mapped Mystery Shop binding cases pass; broader
  shop pixel groups timed out and are not reported as complete suite passes.
- Core/product/gameplay/route metadata/service-route integration: 196 pass. Hall native
  dispatch/reward/UNKNOWN/restart cases pass. Farm native: 22 pass. Commander/recipe: 26 pass.
  Training: 45 pass, seven optional retained-evidence skips. Hall/Training pytest service: 50 pass.
  Other passed service cases: Alliance Shop, Daily Shops, Nanoweapon, Duel and Research.
- Material Production completed claim/start native case passes. Existing Nanoweapon same-visit
  smoke emitted the production/claim/start inputs but fails its old terminal `KEY:BACK`
  expectation; it is not a successful whole-route proof. The unchanged Material Production
  negative-output adapter test also expects `blocked` where the current adapter returns `unresolved`.
  The legacy daily-Nanoweapon test, already deleted in the original dirty workspace, has a stale
  successor expectation; that original deletion is untouched.
- `scripts/check.py` ran its fixed 412-case set: an existing host-profile path in
  `tests/fixtures/alliance_shop_menu/inventory-repaired-entry/provenance.json` fails its guard.
  Its 66 contract-loading errors were subsequently repaired and covered by the passing
  196-case integration group; the whole command is not claimed green.
- Immutable-main static ratchet failed on aggregate integrated-branch debt. Budgets were not
  raised and no suppressions were added. An earlier changed-file Ruff run reported 54 findings.
  Final Core and talent-adapter Pyright have no errors; Help retains optional-ROI diagnostics
  in unchanged code. This is not a clean whole-branch static result.
- All three supported `pnsctl --help` / `automation-service --help` / `serve --help` surfaces
  start with repository `PYTHONPATH` unset. These are offline checks, not native acceptance.

## Earlier resumed development state (historical; superseded above)

- **Acceptance is not queue completion.** #66 has a fully accepted native route
  receipt: integrated source `a4811874`, one owned 1K Food, 129810 to 129809,
  one confirmed authority effect, three inputs and verified Home. #73 now also has
  verified recovered/resumed canonical completion, detailed below. Do not repeat
  either effect to manufacture a receipt. #54's zero-ready pass and #56's
  zero-request visit are not ready-chest or ten-Help acceptance.
- **Latest #72 native visit:** source `7cd33b5`, seven accounted navigation inputs,
  zero purchases/effects and verified terminal Home. Ruins offer handling stopped on
  missing exact offer/in-shop Owned evidence; the one bounded Rare Earth selector
  reveal did not prove that tab's successor. Both per-tab results were retained.
  The route is implemented but purchase acceptance remains `evidence_required`.
- **#73 recovered/resumed completion:** the original Weekly Bioenhance Scheme Buy
  changed Owned 29 to 30, stock 5 to 4 and Alliance Coins 1464257 to 1384257.
  A fresh bounded inspection returned Home and reconciled that exact action
  `b93d1fe8da73cfef9f89badf72993417cd5f40d2213ad44cc568540c9f3e4181`.
  The subsequent canonical route at source `5be0024` completed as
  `ALLIANCE_SHOP_PASS_VERIFIED`, with one prior confirmed action, zero new inputs,
  zero Buy calls and fresh terminal Home. This is recovered/resumed acceptance,
  not relabelling the original failed canary. Evidence:
  `restart-resume-20261108T035832132346Z/alliance-shop73-confirmed-resume-native/`.
- **Other concrete repairs:** #77's actual HOT modal now recognizes offline, but exact
  ordinary-resource balance/debit evidence remains absent (abbreviated Home HUD,
  blurred modal). It must not donate on guessed balances. #70's real-session zoom
  accounting repair passed 43 focused checks and Ruff; its native qualification remains
  open. Ruins wallet/header repair `5bd88fc` passed 47 focused/Home checks and a direct
  actual-pixel observer smoke; no new #69 challenge or chest is inferred.
- **Latest actual guard stops:** #71 reached the Gear Factory radial, not the full
  production/craft screen; no production/craft effect was confirmed. Its dispatched
  non-consequential navigation remains unresolved. `SafetyStore.has_action_block`
  filters consequential actions only: this is not a global native gate.
  #75 still has no confirmed entry/flee cycle; its last overview-header rebind
  failure was reproduced on the actual paired frames and corrected. Two existing
  route-owned Back inputs subsequently verified clean Home without gameplay.
  #76 has not started Research; exact identity/HUD recognition fixes address its
  observed pre-start stops, but admission and native acceptance remain open.
  The current Research Center Atlas binding was revalidated offline on two real
  Home captures; both project to the actual globe-topped building. Root and E
  already share the corrected anchor. No new Atlas edit was warranted; the
  corrected entry still needs a live tap and Research start/debit/timer proof.
- **#67 actual attempts and repairs:** the first native visit sent zero inputs
  before the 60-second service lease expired. Real-frame profiling isolated the
  Home "Rider Camp" label launching Training tier OCR. The reader now defers that
  scan until Training prerequisites are present; the canonical executor also
  renews its existing lease during long recognition, retaining stop/reset/clock
  and generation checks. Supported canonical startup recovery marked the orphan
  FAILED without resetting history. The next visit finished in about 25 seconds,
  still with zero inputs/effects, and exposed the borrowed-session generation
  comparison. Both adapter and native comparisons are corrected. Training remains
  unaccepted; two persisted failures and the unproved Training switch branch remain.
- **#95 actual Military subpath:** source `118d72f` freshly verified exact saved
  Military as already Applied, then returned through the owned Back chain to
  canonical Home. Five navigation inputs were accounted by runtime and SDK;
  zero switches, resources or gameplay effects. Actual captures exposed missing
  header/status OCR, animated-page pixel comparison, overlapping OCR duplicates,
  and premature acceptance of the old source page after an input; these were
  corrected in F through `8771c47`. Evidence:
  `restart-resume-20261108T035832132346Z/commander95-military-owned-roundtrip-20261108T131328027923Z/`.
  This is native helper inspection, not full #95 switch acceptance. Economy and
  Training switch costs/confirmation/effects remain `evidence_required`.
- **#96 latest canonical visit:** source `4cfea07` independently verified saved
  Military already Applied and all three owned Back successors, then opened the
  correct freshly mapped Hall of War radial. Seven navigation inputs, zero
  Dispatch/reward/switch calls, verified accounting. The prior real visit also
  exercised two guarded, measured Atlas pans. Concrete `DirectPanPlan` endpoint
  and PNG-versus-Atlas pixel-identity mismatches were corrected through F
  `eb6be88`; no freshness, overlay or ambiguity guard was removed.
  That radial stop was repaired using current Atlas ownership and isolated
  captions, without repeating the successful building tap. Two finite,
  navigation-only inspections subsequently opened Zombie Zero and its Dispatch
  formation page (one input each, no Dispatch/reward/spend). F `1076b2f`, integrated
  as `6290a77`, replaces failed full-frame menu OCR with bounded actual-label
  recognition: current Today's Highest Dmg is 0 and Attack is a measured gold
  button. Its fresh source guard passed in the live menu-to-formation inspection.
  The SDK stopped at `unknown_successor` on the correct visible Dispatch page:
  its unchanged formation reader still misses Dispatch/Quick Select. Current
  formation has five empty hero slots and 0/160,200 troops. Repair from the
  retained successor, then inspect saved Troop Set 1; do not repeat Attack or
  Dispatch an empty formation. This navigation proof is not route acceptance.
  Six canonical failures remain retained, inspected baseline three, maximum
  attempts three; the first window was rearmed through supported `inspect-rearm`,
  not raw counters or a higher limit. Full Hall acceptance remains
  `evidence_required`. Current game context is the Dispatch formation selection
  page, not terminal Home. Runtime controls remain disabled; the input lock is
  empty. Canonical attempt counts and evidence remain intact.
  Evidence: `restart-resume-20261108T035832132346Z/hall-of-war96-native-current-atlas-identity-20261108T134358611017Z/`
  and `hall96-current-menu-to-formation-20261108T143406693457Z/` under that same
  restart-resume directory.
- **Remaining scenarios:** #54, #69/#56, #77/#72, #70/#71, #75/#76/#78 and
  #95/#96/#67 still need their qualifying finished-route effects.
  Prior manual Duel/Farm/Hall effects and restart-invalidated preset state remain
  reconciliation inputs, not permission to repeat effects. #74 uses baseline/final
  cumulative normal-upgrade verification; its Campaign/150-diamond Reset stays
  unproved. #104 awaits an exact current disconnect episode; do not force an outage.
- **Checks:** device-free `scripts/check.py` passed 411 checks before the newest
  selector/dialog repairs. #73's published inventory repair passed 47 focused checks;
  #72's published selected-Shop guards passed six actual-pixel checks. The integrated
  static ratchet against immutable `c6f0e2fba509dacde136226a7519568550f6b066`
  still has unresolved failures; clean scoped E/F typing checks are not a whole-repo pass.
- **Posture and ownership:** parent is the sole authorized live operator; subagents
  edit offline only. Every finite visit restores service/all route switches OFF and
  retains its authorization, transport, semantic and terminal records. The latest
  controller and read-only snapshot confirm service/every flow OFF; the runtime
  input-lock table is empty. No worker has live authority.
  No merge, deployment or permanent scheduling was performed. Preserve Original captures, unrelated changes
  and owner-source stash `f5c8b264a18b4ad78aaeb0c07e28b199b12ce705`.
- **Evidence roots:** Original `.local-captures/development-sessions/`
  `resumed-queue-20261108T014450968963Z/resource66-repaired/` and
  `restart-resume-20261108T035832132346Z/`, particularly
  `daily-shops72-gold-selector-native/` and
  `alliance-shop73-inventory-repair-native/`. Read their controller results;
  transport success or old receipts alone never establishes current readiness.

## Historical November 7 handoff

The entries below are preserved history. Present readiness and acceptance above
supersede contradictory historical statements; current GitHub owner direction wins.

- **Current priority #104:** fresh `impl/network-disconnect-104-20261107` is stacked on unmerged Wali `96ec81d`; refetched `origin/main` remained `c6f0e2f`. Exact native `[10054]` recognition, canonical restart-safe episode budgets, opt-in owner-bound reconnect/launcher-only relaunch, active capture/dispatch guards and service recovery-only deferral are implemented. No new route registration or controls were added.
- **#104 revised offline proof:** 363 combined recovery/authority/freshness/native/metadata/shared-contract tests pass, including immutable occurrence migration, recovery-only daily/cooldown eligibility, resumed original-source validation, expired pre-input/OCR deadlines, late acknowledgement and launcher restart. Device-free `scripts/check.py`: 413 pass. Actual supported `recover-network --live --yes` with replay-only transport confirms one navigation input/zero launches, a confirmed Core row and RECOVERED SQLite episode, with service/controls unchanged OFF. The reproduced original-deadline bug previously sent one physical fake tap after expiry; its repaired replay sends zero. Previous 69/345 receipts predate these additional fixes. Existing help checks used PYTHONPATH unset; these results are not native acceptance.
- **#104 actual native canary:** current authorization was used through supported `pnsctl development-session recover-network --live --yes`, source `5a0394e`, against Original canonical state: one Confirm, zero launches/spend. Immediate successor was the interrupted Daily Quest screen plus a loading spinner; the old guard stopped as `unexpected_successor`, leaving the episode MANUAL_REQUIRED and its non-consequential Core navigation unresolved. Retain `recover-network-20261107T205836212809Z`; do not retry or relabel that failed run accepted. Separate zero-input `observe-20261107T210024768096Z` later showed Home, outside its original deadline.
- **#104 actual-source repair:** popup dismissal with an unknown/loading successor now permits observation only within the same original deadline; manual/other-modal states still stop immediately. Replay of the actual source/loading/Home captures confirms one fake-transport Confirm, zero launches and a confirmed temporary Core row. The five focused network suites pass 91 tests; device-free check.py passes 413. This is offline proof, not a fresh passed native recovery canary.
- **#104 explicit inspection:** `recover-network --inspect-only --live --yes` uses the existing controller, exclusive lock, Core reconciliation and MANUAL_REQUIRED-to-RECOVERED state transition. It accepts only its own returned zero-cost Confirm with no relaunch, no uncertain gameplay effect, and two fresh verified Home captures; it sends zero inputs/launches. It preserves the original source/deadline/counters/raw failed receipt and records `original_canary_accepted=false`; a fresh invocation is required. The original recovery and launcher/recovered-route acceptance remain `evidence_required`.
- **#104 native inspection proof:** source `b4a2840`, supported `recover-network --inspect-only --live --yes`, retained under `inspect-network-20261107T212317488660Z`, verified two fresh Home captures and reconciled only the returned navigation through existing Core/state APIs. Actual inputs/launches were zero; `original_canary_accepted=false`, fresh invocation required. All eight original canary artifacts remained byte-identical; all 262 service runs were retained. Service/route switches stayed OFF and both service/input owners were released. This does not qualify the original failed recovery canary or its unexercised launcher branch.
- **Owner correction #74:** the strict per-single Back/level-plus-one settlement described below is the existing draft, not the desired final policy. The owner approved baseline/three ordinary taps/final cumulative-level verification, split only for real cap/evolution/shortage needs; its implementation revision follows #104. Tracker #53 and the current #74 comment remain the active plan.

- **Verified starting point:** `origin/main` and Original HEAD were `c6f0e2fba509dacde136226a7519568550f6b066` at startup; this is not a claim about today's remote tip.
- **Review publication:** A–F remain draft PRs #97–#102. Conditional Wali is draft PR #103 on `impl/base-route-wali-20261107`, implementation `32f92b4`, locally integrated with published F `afb57a1`. F includes E `4241edd` and D `142ead5`. No PR merge, deployment or permanent runtime enablement occurred.
- **D scope:** #70 maintains zero-resource, one-slot 21,600-second production: idle start, completed claim/restart, active timer deferral and restart survival. #71v2 requires separately authorized production maintenance in the same visit, then at most one Normal Craft start/reset: exactly 100 Nano Parts/43,200 seconds; claim completed craft. No Exclusive Craft, Daily/D02 ownership or points attribution.
- **D posture/proof:** 18 fixed specs/17 serve routes; twelve legacy operator rows. Original 252 focused tests passed; the later shared-pan hotfix passed 97 relevant tests and device-free check.py406. Three supported pnsctl help surfaces pass with repository PYTHONPATH unset. No D live/device work or acceptance is claimed; controls remain disabled and live acceptance is `evidence_required`.
- **D executable smoke:** fake/replay Home entry performed three bound navigation inputs and one zero-cost production start. Native panel replay verified completed production claim/restart(two effects), plus same-visit production start/craft claim/Normal Craft start(three effects), exact100NanoParts debit/43,200seconds and verified Home. Actual canonical Service/tempSQLite persisted production/craft effects1/2 and six-hour due times; reopen-before-due added zero runs.
- **D integration repairs:** recurring verified effects defer to their proven next timer rather than becoming daily-complete; pending Campaign observation is constructed before typed recurrence validation. Native navigation observations supply required target fields, and Material-tab binding uses the actual ndarray/current text target. The shared mapped-pan dispatcher now receives its native runtime: actual SDK/Core camera replay observed one confirmed pan/rebind, and one unresolved unknown with no identical retry. No safety/freshness guard was weakened.
- **E scope:** #75 Hero Duel, #76 Recommended Research and #78 Food Farm Boost were integrated as disabled canonical routes. Composition is 21 fixed specs/20 serve routes; the existing twelve legacy operator rows remained unchanged. Hall/Training rules are F-only.
- **E posture/proof:** draft PR #101: 337 focused tests pass (two optional skips), check.py410 passes, and both opt-in original Research capture checks separately pass. Actual canonical Service/tempSQLite observed Hero3/Research1/Farm2 effects and zero restart-before-due runs; three supported help surfaces pass with PYTHONPATH unset. No E device/live input or acceptance is claimed; current live acceptance remains `evidence_required`.
- **F scope:** #96 Hall of War and #67 Troop Training are canonical service routes; the Commander Talents helper is reused, with no standalone #95 schedule. Composition is 23 fixed specs/22 serve routes and eleven legacy operator rows; the legacy Troop Training operator runner/validator/aliases are removed. Runtime controls remain disabled.
- **F posture/proof:** the initial integrated gate passed 307 focused tests (eight optional retained-capture skips) and device-free check.py413. Actual Hall consequence/Core/tempSafetyStore replay confirmed dispatch and one reward-row claim (two taps); unknown dispatch stayed unresolved after one tap and denied retry. Actual Service/tempSQLite observed Hall2/Training4 effects, persisted due times, and zero restart-before-due runs. Three supported help surfaces pass with PYTHONPATH unset. Later repair checks are recorded separately below; no F device/live acceptance is claimed.
- **F known-deferral repair:** an actual service/tempSQLite probe exposed unavailable-challenge and unavailable-reward DTOs becoming `BLOCKED` because their wake time was absent. Both now remain `DEFERRED`, retain their zero/one confirmed-action prefixes, and add no input after reopen before due. The 300-second policy re-observation is clipped to the UTC reset; it is not a game cooldown or permission to retry an unknown effect. The repair passed 226 relevant focused tests (eight optional skips) and check.py413.
- **F native-request repair:** the fixed Hall factory incorrectly passed a result validator as a request validator, rejecting a valid canonical `NativeRouteRequest` before device open. Removed that dead hook; the canonical adapter retains result validation. An actual held temporary SQLite input-lock/request probe now passes without opening a device. The repair passed 226 relevant focused tests (eight optional skips) and check.py413; this is offline startup proof, not native live acceptance.
- **F guarded gaps:** every Commander ensure obtains fresh exact Applied proof; no cached readiness or redundant switch. Unknown switch costs/confirmation effects remain `evidence_required`. Hall Vision/import/fresh-capability defects are fixed, but the full current Military/Set1/Dispatch/result/reward/Home scenario still needs authorized native acceptance. Training retains all four approved configurations and a finite 96-input/12-action budget; known shortages defer without blind Train. Fighter/Vehicle boxes remain unavailable without exact current inventory/effect authority; Shooter/Rider boxes are prohibited. Same-namespace legacy box/warehouse history requires reconciliation, never silent removal.
- **Prior B/C offline proof:** after forwarding A, B passed 203 focused tests and check.py401; C passed 286 focused tests and check.py404. Existing temporary-SQLite service smokes committed Ruins/Help and donation/shop/tab effects; reopen-before-due added no runs. These are not D or E validation.
- **Prior route policy:** ten confirmed HOT donations, exact Weekly-or-Other quantity-one shop selection, and independently bounded numeric purchases on both Daily Shops tabs. Partial/UNKNOWN results persist and deny identical retries.
- **Current A:** native per-chest loop, exact same-slot Claimed proof, durable reset/slot journals and verified Home closure are incorporated. A independently passed 212 focused tests (two optional skips), check.py394 and native-driver/journal/adapter offline replay of one aggregate plus five chests.
- **Observed manual chest:** the authorized parent claimed exactly one first glowing chest November 7; retained same-slot open/Claimed is investigative source basis, not native-route acceptance. Never repeat its same-reset work or clear counters. Raw UNKNOWN collection remains, with separate semantic inspection.
- **Resource Item:** exactly one positively identified owned 1K Food item, with owned decrement by one; no Food-balance OCR or Daily ownership. Current native acceptance is `evidence_required`.
- **Runtime posture:** the bounded #54 canary temporarily enabled only its authorized controls; service and all eleven controls were restored OFF. No scheduling deployment or PR merge. Raw source evidence and unrelated user files remain preserved; authorized runtime history is retained.
- **Conditional Wali scope:** #74 now uses hero_upgrade-v4/product authority r21 through the same Hero owner, canonical adapter/native binding/Core journal and disabled `serve --flow wali-upgrade`. Bounded individual normal inputs use one baseline and final cumulative level/exact summed Antiserum debit, with fresh control/quote per tap; no mandatory per-input Back/+1 settlement. Only actual verified normal inputs count toward three/reset; cap/evolution or a real quote/shortage obstruction may split the batch. Standard evolution never credits/resets normal count. Historical confirmed singles remain readable; new execution uses stable reset/first-ordinal batch keys.
- **Wali batch offline proof:** 180 focused semantic/native/adapter/Core/product/metadata/shared-contract tests and device-free check.py413 pass. Actual binding/SDK/runtime/Core/temp-SQLite smoke confirms three individual inputs at changing costs 135/142/149, one final cumulative level5-to8 proof, debit426, one confirmed quantity3 batch intent, eight physical inputs and verified Home. Reopen observes prior count3 and sends zero inputs. Existing meaningful cases cover partial/resume, cap/evolution splits, changing costs, unproved/crashed batches, restart/reset UNKNOWN and duplicate prevention; none are native acceptance.
- **Wali evidence gaps:** current baseline/three-input/final proof and actual bulk-row behavior still require supervised native qualification, with prior same-reset work reconciled first. Historical desktop-derived captures do not supply acceptance or complete compressed evolution-preview quotes. The exact Campaign block and final 150-diamond Reset confirmation remain unverified; no Reset input is admitted and #74 stays open.
- **Original workspace closure:** Original was returned to `main`; the later refetch still found main/origin-main at `c6f0e2fba509dacde136226a7519568550f6b066`. Twenty-two protected state/evidence/user files matched immediately around restoration and again at delivery. Service/all eleven stored controls are OFF, input-owner rows zero and service owner null; no new route controls were initialized. Native inspection/history remains intact. The unattributed missing `tests/test_daily_nanoweapon.py` was left untouched; its author is not inferred.
- **Pit #81:** investigation only. Saved Troop Set 1 populated the observed formation and cancellation preserved five attempts; no final Dispatch/battle/occupation/collection was accepted. Lighter-marker recognition and battle/fatigue/occupation/collection effects remain unproven. No implementation or Reset Field cleanup is promised.
- **Historical handoff:** the [November 2 pre-merge snapshot](../archive/current-handoff-astra-premerge-20261102.md) remains historical; its PR #16 publication/CI instructions are complete or obsolete.

This file grants no live authority.
