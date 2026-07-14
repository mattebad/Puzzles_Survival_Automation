# Current runtime-proof handoff

## 2026-07-14 Bioenhancer Bliss evidence boundary

- Verified repository at `main`, ending implementation HEAD currently recorded by this boundary
  after route/timestamp commits; worktree tracked files were clean before evidence metadata edits.
  Protected runtime evidence remains intentionally untracked.
- Runtime gate passed through `pnsctl`: VM `PnS-BlissOS-PoC` running, worker
  `pns-mvp-help-all-20260713` already up and synced, private ADB connected at
  `192.168.122.79:5555` through loopback `127.0.0.1:5042`, package foreground
  `com.global.ztmslg/com.games37.sdk.AtlasPluginDemoActivity`, profile
  `pns-blissos-poc-virgl-800x1280-v1`, 800×1280.
- Bounded route evidence passed: Home→Quest, Quest→selected Daily, two Daily scroll-up
  successors, and Daily Bioenhancer Go. Exact selected row was `bioenhancer_research 0/1`;
  Daily Go target was `(554,870)-(731,933)`, one navigation tap, direct successor
  `BIOENHANCER` confirmed by `nav-daily-bioenhancer-go-1784059479`.
- The app opens Bioenhancer Research directly. No Nova screen or Nova Research intermediary was
  observed. A historical attempt expecting `NOVA` remains an unresolved navigation-only record;
  it is not consequential and is not treated as an active consequential blocker.
- Fresh timestamped pre-dispatch frame proves Bioenhancer Research, Free Research 1x target
  `(94,1133)-(345,1216)`, separate Research 10x `(455,1133)-(706,1216)`, single quantity,
  visible free state, no observed overlay, and zero cost. Exact target is annotated on a copy;
  raw source remains unchanged.
- No Free Research or Research 10x input occurred. No research transaction, Daily progress
  change, Claim, task-state row, runtime registration, or scheduler eligibility changed.
  Evidence boundary is `PRE_DISPATCH_READY` / matrix `EVIDENCE_GATED`; game-day identity was not
  independently observable, so explicit supervised approval and positive `0→1` reconciliation
  remain required.
- Canonical package:
  `evidence/sessions/20260714-daily-flow-acquisition/bioenhancer-free-pre-dispatch.json`
  and `.sha256`. Claim remains an independent action.

## 2026-07-14 Daily Supply Depot selected-row adapter

- Completed `DQ-FLOW-SUPPLY-DEPOT` as `tasks/daily_supply_depot.py`, composing the existing
  free, known non-premium Supply Depot contract with selected-Daily `supply_depot` row binding.
- The adapter requires one current-frame free collection per pulse and exactly enough same-day
  successors to reach Daily progress 5/5. Five focused tests cover ownership, reward/cost guards,
  five-count arithmetic, Main/static negatives, Claim separation, and zero dispatch.
- Matrix remains evidence-gated, unregistered, and scheduler-ineligible; no live input, journal,
  lease, task-state, or gameplay state changed.

## 2026-07-14 Daily Bioenhancer selected-row adapter

- Completed `DQ-FLOW-BIOENHANCER` as `tasks/daily_bioenhancer.py`, composing the existing
  free-single Bioenhancer research contract with selected-Daily `bioenhancer_research` row
  binding.
- The adapter requires one current-frame free research action and a same-day positive result or
  cooldown transition with Daily progress 0/1. Five focused tests cover ownership, transaction
  guards, successor arithmetic, Main/static negatives, Claim separation, and zero dispatch.
- Matrix remains evidence-gated, unregistered, and scheduler-ineligible; no live input, journal,
  lease, task-state, or gameplay state changed.

## 2026-07-14 disabled resource-building boost contract

- Completed `DQ-FLOW-RESOURCE-BOOST` as resource-building identity, resource, duration, and cost
  replay in `tasks/resource_boost_disabled.py`. It binds the exact current-frame boost control and
  same-day boost successor; resource-building boost dispatch is always blocked.
- Synthetic replay fixtures and five focused tests cover building/resource/duration/cost guards,
  Main/static/ambiguous rejection, boost-state arithmetic, Claim separation, and no-dispatch
  behavior. Row remains disabled, unregistered, and scheduler-ineligible; no live or persistent
  state changed.

## 2026-07-14 disabled Ruins Challenge contract

- Completed `DQ-FLOW-CHALLENGES` as Ruins Challenge identity/cost/result replay in
  `tasks/challenge_disabled.py`. It binds selected-Daily challenge identity, exact Enter control,
  known AP cost, and same-day result; challenge entry is always blocked.
- Synthetic replay fixtures and five focused tests cover Ruins versus Ultimate/Main separation,
  cost/AP guards, result arithmetic, ambiguous rejection, Claim separation, and no-dispatch
  behavior. Row remains disabled, unregistered, and scheduler-ineligible; no live or persistent
  state changed.

## 2026-07-14 disabled Speedup contract

- Completed `DQ-FLOW-SPEEDUP` as 180-minute timer/item replay in `tasks/speedup_disabled.py`. It
  binds selected-Daily timer identity, exact non-premium item, quantity, and same-day timer
  successor; item consumption and speedup dispatch are always blocked.
- Synthetic replay fixtures and five focused tests cover timer/item/quantity guards, exact
  180-minute arithmetic, Main/static/ambiguous rejection, Claim separation, and no-dispatch
  behavior. Row remains disabled, unregistered, and scheduler-ineligible; no live or persistent
  state changed.

## 2026-07-14 disabled Alliance Technology donation contract

- Completed `DQ-FLOW-DONATION` as Alliance Technology target/resource/count replay in
  `tasks/donation_disabled.py`. It binds selected-Daily tech identity, exact Donate control,
  known resource amount, and same-day successor; donation dispatch is always blocked.
- Synthetic replay fixtures and five focused tests cover target/resource guards, count/resource
  arithmetic, Main/static/ambiguous rejection, Claim separation, and no-dispatch behavior. Row
  remains disabled, unregistered, and scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 disabled purchase contracts

- Completed `DQ-FLOW-PURCHASES` as parameterized `tasks/purchases_disabled.py` semantics for Box,
  Ruins Shop, Rare Earth Shop, and Alliance Shop. Each variant binds selected-Daily objective,
  exact shop/offer/item, known currency cost, and same-day item/currency successor; purchase
  dispatch is always blocked.
- Synthetic replay fixtures and six focused tests cover four-way ownership, cost/currency/reward
  guards, Main/static/ambiguous rejection, offline arithmetic, Claim separation, and no-dispatch
  behavior. All four rows remain disabled, unregistered, and scheduler-ineligible; no live or
  persistent state changed.

## 2026-07-14 disabled Hero Upgrade contract

- Completed `DQ-FLOW-HERO-UPGRADE` as selected-hero/material/level replay in
  `tasks/hero_upgrade_disabled.py`. It binds selected-Daily hero identity, exact Upgrade target,
  known material/cost state, and same-day successor; hero upgrade dispatch is always blocked.
- Synthetic replay fixtures and five focused tests cover hero/material identity guards, level
  arithmetic, Main/static/ambiguous rejection, Claim separation, and no-dispatch behavior. Row
  remains disabled, unregistered, and scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 disabled Tech Upgrade contract

- Completed `DQ-FLOW-TECH-UPGRADE` as prerequisite/level replay in
  `tasks/tech_upgrade_disabled.py`. It binds selected-Daily technology identity, prerequisites,
  exact Upgrade target, queue/cost state, and same-day successor; research dispatch is always
  blocked.
- Synthetic replay fixtures and five focused tests cover prerequisite/identity guards, level
  arithmetic, Main/static/ambiguous rejection, Claim separation, and no-dispatch behavior. Row
  remains disabled, unregistered, and scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 disabled Hero Duel contract

- Completed `DQ-FLOW-HERO-DUEL` as event/Join/progress replay in
  `tasks/hero_duel_disabled.py`. It binds selected-Daily event identity, active attempts, exact
  Join control, current-day provenance, and participation successor; PvP dispatch is always
  blocked.
- Synthetic replay fixtures and five focused tests cover event and target identity, Main/static/
  ambiguous rejection, participation arithmetic, Claim separation, and no-dispatch behavior.
  Row remains disabled, unregistered, and scheduler-ineligible; no live or persistent state
  changed.

## 2026-07-14 disabled Building Upgrade contract

- Completed `DQ-FLOW-BUILDING-UPGRADE` as generic `tasks/building_upgrade_disabled.py` identity
  and level replay. It rejects Vehicle Depot at both identity and Main-Quest source boundaries,
  requires exact current-frame building/Upgrade/cost/queue evidence, and blocks every dispatch.
- Synthetic replay fixtures and five focused tests cover generic successor arithmetic, Vehicle
  Depot/Main/static negatives, stale/cost/queue guards, Claim separation, and no-dispatch
  behavior. Row remains disabled, unregistered, and scheduler-ineligible; no live or persistent
  state changed.

## 2026-07-14 disabled Training contract

- Completed `DQ-FLOW-TRAINING` as counter-only `tasks/training_disabled.py` semantics for
  Fighter, Rider, Shooter, and Vehicle. It binds each selected-Daily row to exact unit/facility,
  queue capacity, known cost, tier, and current-day evidence, then blocks every dispatch under
  `DISABLED_POLICY`.
- Synthetic replay fixtures and six focused tests cover four-way ownership, queue arithmetic,
  resource/queue guards, Main/static negatives, Claim separation, and no-dispatch behavior. All
  four rows remain disabled, unregistered, and scheduler-ineligible; no live or persistent state
  changed.

## 2026-07-14 offline Gathering family

- Completed `DQ-FLOW-GATHERING` as parameterized `tasks/gathering.py` semantics for proven Wood,
  Steel, and Gas only. Authorization binds selected-Daily resource identity, exact current-frame
  node, node level, unoccupied/not-targeted state, available march slot, known formation/duration,
  and Bliss-native provenance. Gather Food remains outside catalog scope.
- Synthetic replay fixtures and six focused tests cover variant ownership/cardinality, node and
  march guards, Main/static/selected-Daily negatives, transaction semantics, positive outbound
  or result successor, and pure one-pulse output. Contract remains unregistered and
  scheduler-ineligible; no live input or gameplay state changed.

## 2026-07-14 disabled Stamina contract

- Completed `DQ-FLOW-STAMINA` as counter-only `tasks/stamina_disabled.py` semantics. It binds
  selected-Daily stamina-counter observations to current-day Bliss-native evidence and verifies
  exact offline counter arithmetic; it has no transaction specification or executable spend path.
- Synthetic replay fixtures and five focused tests cover valid counter replay, same-day delta,
  Main/static/uncertain rejection, Claim separation, and unconditional disabled-policy dispatch
  blocking. Matrix remains `DISABLED_POLICY`, unregistered, and scheduler-ineligible. No live
  input, journal, lease, task-state, or gameplay state changed.

## 2026-07-14 offline Zombie Lair contract

- Completed `DQ-FLOW-ZOMBIE-LAIR` as pure `tasks/zombie_lair.py` semantics composed with the
  shared World/stamina primitive. Authorization requires exact Lair identity, non-60 allowlisted
  level, current-frame Join target, available march slot, bounded stamina cost, and no combat/
  overlay ambiguity.
- Synthetic replay fixtures and five focused tests cover Lair target and stamina binding,
  level-60/Main/static/full-march rejection, level/march/budget guards, exact same-day stamina
  delta plus defeat/result postcondition, and pure one-pulse output. No registration, scheduler
  eligibility, live input, or gameplay state changed.

## 2026-07-14 offline World/stamina primitive

- Completed `DQ-FLOW-WORLD-STAMINA-ENGINE` as pure `tasks/world_stamina.py` route and resource
  reconciliation semantics. It recognizes current-frame World destinations, explicit stamina/AP
  budgets, panel-local targets, stable same-day successors, and Bliss-native provenance; it never
  authorizes coordinate input or resource dispatch.
- Synthetic replay fixtures and five focused tests cover Lair/resource family ownership, current
  and policy budget bounds, Main/static/stale/uncertain rejection, stable route postconditions,
  and pure replay output. Primitive is a support flow, unregistered, and scheduler-ineligible.

## 2026-07-14 offline Campaign AP contract

- Completed `DQ-FLOW-CAMPAIGN-AP` as pure `tasks/campaign_ap.py` semantics for one bounded
  allowlisted Sweep or Auto Complete action. Authorization requires selected Campaign state,
  known stage, exact current-frame AP target, readable AP, explicit positive budget, cost within
  budget, and no refill/battle state.
- Synthetic replay fixtures and five focused tests cover Sweep/Auto Complete variants, AP budget
  and resource guards, Main/static-reference rejection, exact same-day AP delta plus result
  postcondition, and pure one-pulse output. Contract is unregistered and scheduler-ineligible;
  no live input or gameplay state changed.

## 2026-07-14 offline shared enhancement contract

- Completed `DQ-FLOW-ENHANCE-GEAR` with shared `tasks/enhancement.py` semantics and Gear
  ownership. Authorization requires Commander Info Gear state, equipped selected item, exact
  current-frame Enhance target, one known available one-star material, quantity one, Auto Select
  disabled, current day, locked profile provenance, and no overlay/reset guard.
- Synthetic replay fixtures and five focused tests cover Gear authorization, Chip-versus-Gear
  family ownership, Main-negative rejection, material/target safety guards, same-item positive
  postconditions, and pure one-pulse results. Gear, Chip, and Module variant contracts are now
  complete offline. No registration, scheduler eligibility, journal, task-state, lease, or
  gameplay state changed.

## 2026-07-14 offline Nanoweapon contract

- Completed `DQ-FLOW-NANOWEAPON` as a pure `tasks/nanoweapon.py` Craft Weapon contract. It
  requires selected Craft Weapon state, known recipe/material availability, approved duration
  policy, exact current-frame target, explicit zero cost and quantity one, current game day,
  locked profile provenance, and a positive result, count, or timer postcondition.
- Added synthetic replay fixtures and five focused tests covering free recipe authorization,
  Material Production/static-reference rejection, recipe/material/target/policy guards, same-day
  postconditions, and pure one-pulse results. The module is offline-only, unregistered, and
  scheduler-ineligible; no runtime or gameplay state changed.

## 2026-07-14 offline Bioenhancer contract

- Completed `DQ-FLOW-BIOENHANCER` as a pure `tasks/bioenhancer.py` contract for one explicit
  free-single Bioenhancer research action. It requires selected Bioenhancer state, free banner,
  exact current-frame target, explicit zero cost and quantity one, current game day, locked
  profile provenance, and a positive result, count, or cooldown postcondition.
- Added synthetic replay fixtures and five focused tests covering positive authorization, paid and
  static-reference rejection, target/cost/safety guards, same-day postconditions, and pure
  one-pulse results. The module is exported for offline use only; it is not registered in
  `pnsctl`, does not send input, and leaves scheduler eligibility false.
- Matrix, human-readable status, handler status, backlog, and prompt index now record the offline
  contract while preserving evidence-gated promotion and the exact 31-objective catalog.

## 2026-07-14 evidence retention audit and compaction

- Canonical branch remained `main`; the policy/tooling boundary was committed as `fc96e84`.
- The streaming dry-run classified 4,660 evidence files / 1,888,103,865 bytes: tracked
  1,511/425,828,236, untracked 2,253/1,447,595,565, and ignored 896/14,680,064. It protected all
  journals and sidecars, fixtures, Bliss runtime templates, referenced support, unresolved action
  evidence, and decisive evidence. Only 1,761 exact duplicates or repeated identical frames were
  eligible, totaling 1,278,502,180 bytes.
- Those candidates were archived outside the repository at
  `../Puzzles_Survival_Automation_evidence_archive/`. The archive verification passed with 1,761
  checked entries and no errors; its measured size is 133,173,029 bytes across 137 unique blobs,
  including 131,353,624 deduplicated blob bytes. No tracked evidence was removed.
- After compaction, local `evidence/` is 609,601,685 bytes across 2,899 files. Tracked evidence
  remains 425,828,236 bytes; 169,093,385 untracked bytes and 14,680,064 ignored journal-sidecar
  bytes remain. The active-checkout recovery is 1,278,502,180 bytes.
- Git history was not rewritten, repacked, expired, or force-pushed. Current `.git` is
  433,046,304 bytes, with 1,001 reachable evidence blobs totaling 291,331,222 bytes and a
  447,731-byte history-only evidence upper bound. The local audit JSON remains ignored under
  `artifacts/`; `.local-reference/` and protected local files were unchanged.
- Focused evidence/reference validation passes 17/17; the non-OpenCV suite passes 131/131. The
  full discovery reaches 137 tests but remains locally limited by six pre-existing `cv2` import
  errors. No live runtime worker, lease, or gameplay input was started during cleanup.

## 2026-07-14 offline generalized Daily Claim contract

- Added `tasks/available_daily_claim.py` as the generalized contract; the passed Personal Might
  Claim path remains unchanged. The generalized contract accepts any ordinary completed Daily Quest
  objective only when the selected Daily screen, exact row-local Claim, explicit
  `none`/zero/quantity-one cost, current day, locked profile, source hash, and Bliss-native
  provenance are all present.
- Synthetic fixtures cover a non-Personal-Might `Gather Food` contract-positive case plus Go and
  static-reference negatives. Wrong target/ROI, non-free cost or quantity, milestone, clipped,
  overlay, reset, and unchanged-postcondition cases fail closed. The module is not registered in
  `pnsctl` and does not send input.
- Generalized Daily Claim, Phase D, and reference tests pass 21/21; the full non-OpenCV suite
  passes 136/136. The authoritative discovery remains limited only by the six
  existing `cv2` import errors. No image capture, ADB operation, or live gameplay input occurred.
- Fresh Bliss-native generalized Daily Claim target and positive-postcondition evidence remain
  absent; Phase E dispatch stays disabled.

## 2026-07-14 offline activity milestone-chest contract

- Added `tasks/activity_milestones.py` as a separate pure contract for a ready activity milestone
  chest. It requires the exact milestone screen/panel, ready state, `MILESTONE_CHEST` target,
  explicit `none`/zero/quantity-one cost, current day, locked profile, source hash, and
  Bliss-native provenance.
- Synthetic fixtures cover a ready chest, a locked/not-ready chest, and static-reference evidence.
  Wrong target/panel, non-free cost or quantity, overlay, reset, and unchanged chest/points
  postconditions fail closed. The module is not registered in `pnsctl` and sends no input.
- Activity milestone plus prior Phase E, Phase D, and reference tests pass 33/33. No image capture,
  ADB operation, or live gameplay input occurred; the ready milestone target and positive-open/
  points evidence remain absent.

## 2026-07-14 offline free Supply Depot contract

- Added `tasks/supply_depot.py` as a pure contract for a free Supply Depot collection. It requires
  the exact Depot screen/panel target, ready collection state, known non-premium reward, explicit
  `none`/zero/quantity-one cost, current day, locked profile, source hash, and Bliss-native
  provenance.
- Synthetic fixtures cover known basic supplies, premium reward, and static-reference cases.
  Unknown reward, non-free, not-ready, wrong-target/panel, overlay, reset, and unchanged collection
  postconditions fail closed. The module is not registered in `pnsctl` and sends no input.
- The Supply Depot contract plus all prior Phase E, Phase D, and reference tests pass 38/38. Fresh
  Bliss-native free Depot target and positive collection evidence remain absent.

## 2026-07-14 offline free recruitment contract

- Added `tasks/free_recruitment.py` as a pure contract for one free recruitment. It requires the
  selected Recruitment screen, explicit `FREE` mode and banner, exact target, zero cost and
  quantity-one semantics, current day, locked profile, source hash, and Bliss-native provenance.
- 10x/premium, static-reference, wrong-target/panel, no-free-banner, non-free,
  unknown-confirmation, and unchanged-result/count fixtures fail closed. A result identity or
  positive recruitment-count increase is required; the module is not registered in `pnsctl`.
- Free recruitment plus all prior Phase E, Phase D, and reference tests pass 43/43. No image
  capture, ADB operation, or live gameplay input occurred; fresh Bliss-native recruitment evidence
  remains absent.

## 2026-07-14 Daily five-count recruitment adapter

- Added `tasks/daily_recruitment.py` to bind the selected Daily `recruit_noahs_tavern` row to the
  shared free Tavern contract. It requires exactly one free-single successor per pulse and exact
  count/progress arithmetic through 5/5.
- Synthetic replay covers five-count cardinality, selected-row ownership, Main/ambiguous rejection,
  Claim separation, and zero dispatches. The objective remains evidence-gated, unregistered, and
  scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 Daily Nanoweapon adapter

- Added `tasks/daily_nanoweapon.py` to bind selected Daily `craft_nanoweapon` to the shared Craft
  Weapon contract. It requires one exact free known-recipe craft and a same-day Daily 0/1
  successor; craft transport remains evidence-gated.
- Five focused tests cover selected-row ownership, recipe/material/tab guards, one-craft
  cardinality, Main/static/ambiguous rejection, Claim separation, and zero dispatch. The objective
  remains unregistered and scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 Daily Gear enhancement adapter

- Added `tasks/daily_enhancement.py` to bind selected Daily `enhance_gear` to the shared Gear
  enhancement contract. It requires exact equipped Gear/one-star-material semantics and a same-day
  Daily 0/1 successor; enhancement transport remains evidence-gated.
- Five focused tests cover Gear ownership, family boundaries, material/cost guards, successor
  proof, Main/static rejection, Claim separation, and zero dispatch. Chip and Module remain
  downstream variants; no live or persistent state changed.

## 2026-07-14 Daily Chip enhancement adapter

- Extended `tasks/daily_enhancement.py` with selected Daily `enhance_chip` ownership over the
  shared Chip contract. It requires exact equipped Chip/one-star-material semantics and a same-day
  Daily 0/1 successor; enhancement transport remains evidence-gated.
- Five focused tests cover Chip/Gear distinction, material guards, successor proof, Main/static
  rejection, Claim separation, and zero dispatch. Module remains downstream; no live or persistent
  state changed.

## 2026-07-14 Daily Module enhancement adapter

- Extended `tasks/daily_enhancement.py` with selected Daily `enhance_module` ownership over the
  shared Module contract. It requires exact equipped Module/one-star-material semantics and a
  same-day Daily 0/1 successor; enhancement transport remains evidence-gated.
- Five focused tests cover Module/Gear/Chip distinction, material guards, successor proof,
  Main/static rejection, Claim separation, and zero dispatch. All enhancement variants remain
  unregistered and scheduler-ineligible; no live or persistent state changed.

## 2026-07-14 Daily Campaign AP adapter

- Added `tasks/daily_campaign_ap.py` to bind selected Daily `consume_ap` to the shared Campaign
  Sweep/Auto Complete contract. It requires exact bounded AP cost and matching Daily progress,
  with one pure replay action and no transport.
- Five focused tests cover selected-row ownership, AP budget/cost guards, exact delta/progress,
  Main/static/oversized-action rejection, Claim separation, and zero dispatch. The objective
  remains evidence-gated, unregistered, and scheduler-ineligible.

## 2026-07-14 Daily Zombie Lair adapter

- Added `tasks/daily_zombie_lair.py` to bind selected Daily `defeat_zombie_lair` to the shared
  World/stamina and Lair contract. It requires exact allowlisted Lair identity, march slot,
  bounded stamina, and a same-day Daily 0/1 defeat/result successor.
- Five focused tests cover selected-row ownership, level/march/stamina guards, exact result,
  Main/static/combat rejection, Claim separation, and zero dispatch. The objective remains
  evidence-gated, unregistered, and scheduler-ineligible.

## 2026-07-14 offline Phase F scheduler contract

- Added `tasks/scheduler.py` with deterministic serializable task state and a one-pulse candidate
  selector. It binds state to `game_day_id`, selects at most one due task, and requires the external
  lease-valid/no-unresolved gates before selection.
- Verified matching completion keys are the only path to `DONE`; failed-safe, unresolved,
  mismatched/unverified completion, wrong-day, lease, and backoff cases fail closed. JSON snapshot
  round-tripping is deterministic. The module does not replace the SQLite action journal and is not
  registered in `pnsctl`.
- Focused scheduler tests pass 8/8. Phase E offline contract tests remain passing; no image capture,
  ADB operation, or gameplay input occurred. Production SQLite-backed task-state integration remains
  a later offline boundary.

## 2026-07-14 SQLite-backed Phase F task state

- Added the v1→v2 forward migration to the existing `SafetyStore`, introducing only a `task_state`
  table and `SQLiteTaskStateRepository`; action rows, audit lifecycle, lease, and unresolved-action
  semantics remain unchanged.
- Task state persists task/game-day/completion identity, status, due time, revision, and reason.
  Revision rollback and completion-key changes are rejected, and every update emits a deterministic
  audit event. A v1 database migrates forward without losing the action/journal tables.
- Persistence/core/scheduler tests pass 57/57; the full non-OpenCV suite passes 170/170. The full
  discovery reaches 176 tests with only the six known local `cv2` import errors. No image capture,
  ADB operation, or live gameplay input occurred.
- This is persistence infrastructure only; Phase E live promotion and worker integration remain
  gated and the SQLite action journal remains authoritative for consequential outcomes.

## 2026-07-14 persisted scheduler integration

- Added `SQLiteBackedOnePulseScheduler`, a thin adapter that reloads `TaskState` snapshots from the
  existing repository, persists backoff/result/unresolved/reconciliation mutations, and retains the
  external lease/unresolved gates. It does not send input or replace the action journal.
- Restart tests pass persisted due times, completion, unresolved blocking, and positive
  reconciliation. Focused scheduler/state/core coverage passes 59/59; the full non-OpenCV suite
  passes 172/172. Full discovery reaches 178 tests with only the six known local `cv2` import errors.
- Phase F offline state/scheduler integration is complete for this boundary. Worker wiring,
  handler-policy review, and all Phase E live promotions remain separate gates.

## 2026-07-14 Phase E evidence gate

- Fresh selected Daily Quest inventory after Phase D shows 5 points, only `Go` rows, and no ready
  milestone. No additional input is authorized from this frame.
- Remaining milestone, Depot Free, and recruitment Free flows lack Bliss-native exact pre/post
  evidence. Static `GNB-DAILY-*` coordinates remain non-authorizing.
- Phase E resumes only after a fresh eligible control and its free/cost-negative state are captured.

## 2026-07-13 Personal Might leaderboard live evidence

- Exact Check ROI `(590,245)-(775,315)` dispatched one tap at `(682,280)`.
- First post frame positively showed Personal Might Rank leaderboard; journal confirmed one
  transport call.
- Raw leaderboard binds header `(150,0)-(650,70)`, rank-one enabled gold thumbs-up
  `(690,155)-(755,220)`, and Back `(45,5)-(130,60)`.
- Praise target is icon-only and requires header + local template + gold HSV occupancy.
- Phase C route validation passed with zero Praise/Claim inputs.
- First Phase D resume attempt sent zero inputs: startup omitted the already-open Personal Might
  leaderboard and defaulted to Home, then three Home recognitions failed before transport. Startup
  now recognizes explicit resume states and treats every other screen as `UNKNOWN`.
- Phase D Praise is live-confirmed: one tap at `(722,187)`, zero cost, one transport call, and
  positive postcondition. Evidence: `live-praise-success-018/praise-{pre-dispatch,result}.json`.
- Selected Daily Quest now shows exact first-row `Praise 1x in Personal Might Rank (1/1)` with a
  row-local gold `Claim`. Evidence: `live-daily-claim-evidence-019/`.
- Separate Claim confirmed: exact ROI `(590,438)-(695,495)`, tap `(642,466)`, one zero-cost
  transport call, and positive row-disappearance postcondition. Phase D passed. Evidence:
  `live-claim-success-020/`.

## 2026-07-13 corrected Rankings live navigation

- Exact Rankings ROI `(602,1138)-(690,1167)` dispatched one tap at `(646,1152)`.
- First post frame positively showed Leaderboard with Personal Might Rank; journal confirmed one
  transport call. No Help WebView appeared. Praise and Claim inputs were zero.
- Raw successor binds first-row identity `(170,220)-(560,325)` and Check
  `(590,245)-(775,315)`.
- Personal Might row and Check coexist; separate row tap was removed. Next evidence-only action is
  one Check navigation input, then stop before Praise.

## 2026-07-13 GnBots profile/navigation Phase C preparation

- Raw Rankings target is now `(602,1138)-(690,1167)`, center `(646,1152)`. Historical broad center
  `(400,1152)` is removed from the Personal Might route.
- Personal Might and Back anchors are explicitly provisional and block with
  `ANCHOR_EVIDENCE_REQUIRED`; false Home fixture provenance no longer authorizes them.
- NavigationRunner now enforces declared target/postcondition anchors, old-anchor disappearance,
  recognized foreground successors, and production-validated anchor gates.
- Popup handling is limited to VIP Points reset and Help WebView, one handler per frame; unknown,
  cost, resource, and premium dialogs block.
- Full suite passes 172 tests. No live input occurred. Phase C remains in progress until corrected
  Rankings and downstream Personal Might evidence is captured.

## 2026-07-13 GnBots calibration Phase B

- Development-only `calibration/transform.py` implements all five required candidate models,
  point/normalized-ROI transforms, viewport insets, affine fitting, residuals, safe containment,
  and multi-anchor screen-family correction validation.
- Direct 2× remains simplest global starting candidate; a provisional bottom-navigation correction
  is supported by Quest and More. No transformed output can authorize production input.
- Raw 800×1280 Rankings OCR bounds are `(602,1138)-(690,1167)`, center `(646,1152)`. Existing
  broad target center `(400,1152)` is a wrong binding and explains Help WebView interception.
- Calibration/reference focused suite passes 16 tests. Phase B passed; Phase C is ready.
- Missing Personal Might, Claim-positive, Town/world, and march screens remain explicit evidence
  dependencies. No live input occurred.

## 2026-07-13 GnBots static-reference Phase A

- `.local-reference/` is excluded only in `.git/info/exclude`; it remains read-only, unstaged, and
  unavailable to production runtime.
- `docs/research/gnbots_trial_reference_manifest.md` and `.json` normalize relevant flows across all
  12 authorized modules with stable IDs, both source xywh and normalized xyxy ROIs, matcher
  settings, waits, swipes, loop bounds, recovery/completion semantics, direct/inferred status,
  unresolved helpers, and vendor weaknesses.
- No vendor JavaScript, binary, service, selector, or PNG was executed or promoted.
- `tests.test_reference_manifest` passes 5 tests, including exact ROI endpoint normalization and
  production dependency rejection.
- Phase A passed. Next unblocked item is Phase B coordinate calibration. Existing Personal Might,
  popup, backlog, handoff, tests, and retained evidence changes remain preserved.

## 2026-07-13 Personal Might Praise popup binding correction

- The narrow `PersonalMightPraiseHandler`, named route contracts, reset-time popup dismissal
  route, checked-in `pnsctl run-task --task praise` registration, and exact Daily Quest Claim
  reconciliation contracts are implemented and pass focused offline validation.
- Fresh runtime evidence positively recognized the logged-in reset popup as `Get Pts` with
  `Log in every day to get VIP pts`. Review showed the prior ROI `(200,590)-(440,710)` and
  tap `(320,650)` were above the actual Close button, over streak text. Correct visual binding
  is button ROI `(260,750)-(540,870)`, OCR `Close` bounds `(363,795)-(436,817)`, proposed
  center `(400,810)`.
- One prior navigation-only `DISMISS_RESET_POPUP` transaction was authorized and dispatched
  exactly once at the misbound ROI. Immediate and three post frames were identical; it was
  reconciled as proven no-effect in
  `evidence/sessions/20260713-personal-might-praise/live-popup-unresolved-005/`.
- Corrected live attempt used detected button bounds `(277,767)-(523,847)` and one tap at
  `(400,807)`. Mandatory full-frame artifact passed, including literal `Close`, title/body
  identity, interior margin, center-y gate, and old-point negative. Dispatch succeeded and the
  operator directly confirmed the popup disappeared. Executor failed to classify the resulting
  startup surface, so retained action `reset-popup-close-1783994269-2` still records unresolved;
  no second Close tap was sent.
- Phase 1 is live-confirmed by direct observation; journal reconciliation remains required.
  Phase 2 started from the retained Speedup Help surface but stopped after two equivalent
  `normalize-alliance-to-home` failures: first source target recognition failed; after binding
  the fixed-profile Back ROI to positive Speedup Help identity, immediate revalidation cancelled
  with `OVERLAY_STATE_CHANGED` before transport. No Praise or Claim input occurred. Evidence:
  `evidence/sessions/20260713-personal-might-praise/live-corrected-popup-006/`. Task worker and
  private task ADB were removed; VM remains running, backup intact, and no task listener remains.
  Phase 2 blocker evidence is retained in `live-phase2-route-007/` and `live-phase2-route-008/`.

## 2026-07-13 Alliance Help semantic correction

- The historical `(641,302)` action targeted the upper row-level button labeled Help at
  `(556,274)-(727,330)`. Its correct semantic kind is `ALLIANCE_HELP_ONE`; the visible request
  disappeared, proving one individual request was processed. Historical SQLite and screenshots
  remain immutable.
- Actual `ALLIANCE_HELP_ALL` is a separate lower-screen target at `(277,1188)-(523,1268)`, center
  `(400,1228)`. Code requires the literal Help All identity/template plus enforced lower-screen,
  separation, clipping, and interior-tap geometry. A candidate near `(641,302)` is denied.
- The Help allies catalog row is `LIVE_VALIDATED` for both individual Help and the actual lower
  Help All control.
- The actual lower action `alliance-help-1783986842` passed the pre-dispatch artifact and sent
  exactly one tap at `(400,1228)`. The first post frame positively contains the transient exact
  message `No help request currently`; later frames returned to Speedup Help. The immutable source
  journal is retained and the reconciled copy is confirmed with zero unresolved/nonterminal actions.
- MVP-QUEST-TO-CLAIM remains Blocked; no Claim or Daily Quest completion is proven, and
  M6-DQ-TRANSITION-CORPUS remains downstream.

## 2026-07-13 live Daily Quest inventory and unresolved Alliance Help action

- The current run used the selected Daily Quest gate and a complete bounded overlapping-scroll
  inventory. The list contained no ordinary Claim row. It included the exact Help allies row at
  0/10; other rows were upgrades, training, combat, stamina/AP, gathering, purchases, research,
  enhancements, donation, Supply Depot, or other unsupported/strategic actions. Full inventory and
  frame provenance are retained in
  evidence/sessions/20260712-mvp-quest-to-claim/live-daily-inventory-20260713/.
- Help allies Go was used only as navigation and its destination was corrected from a temporary
  Cash Mall-first classifier to ALLIANCE using the retained post OCR: Alliance coin header,
  Daily reset time 19:00:00, the Build Lv.20 Gas Field request, and Help 0/30. No purchase
  control was touched.
- The first supported task handler is AllianceHelpHandler, committed in c1b32e7. Reset
  reconciliation assigned daily-2026-07-13 outside the configured guard. One exact zero-cost Help
  action was authorized and dispatched exactly once at (650,350). The immediate post-dispatch
  frame remained Help 0/30, so the expected positive postcondition was not proven and
  alliance-help-20260713-001 is unresolved. No retry or further input was sent.
- The unresolved journal state is intentionally preserved. The lease was released only after
  journal reconciliation; the task worker and task ADB server were removed afterward. The game
  remains on Alliance Help so the unresolved live evidence is not destroyed. No Claim input,
  objective completion, spend, account, combat, or OS input occurred.

Recorded: 2026-07-13, America/Chicago

## 2026-07-13 live continuation

- The focused typed-task refactor is committed in `e24b304`, with the local Quest successor
  correction in `1c87219`; the fixed-profile navigation contract remains local-ROI based and does
  not require whole-frame equality.
- The fresh continuation started from the approved private unprivileged worker. One verified
  promotional Back reached Home/Base, Home→Quest and Quest→Daily each dispatched once and were
  confirmed from fresh local-ROI successor evidence without retry, and two bounded Daily Quest
  list swipes were dispatched through the safe-action executor.
- Daily Quest was positively recognized, but current points/reset text was not readable enough to
  assign a current `game_day_id`. The visible objectives were Vehicle Depot upgrade, Ultimate
  Challenge, Hunt Zombie, Train Fighter, Own Lv.211 Hero, Gathered Food, and Attack a player's
  Headquarters and win. None is a supported zero-cost R1 handler, and no ordinary Claim row,
  Alliance Help objective, or explicitly free Supply Depot objective was present. No Go or Claim
  input occurred. MVP remains Blocked.
- The live schema-v1 journal is retained at
  `evidence/sessions/20260712-mvp-quest-to-claim/live-20260713/actions.sqlite3`; all actions are
  terminal, with zero unresolved/nonterminal records and a released lease. The task worker and
  its ADB server were removed after evidence preservation; the game was force-stopped; no task
  listener or tunnel remains; the VM is running and RT-017 is intact.
- Full dependency-complete offline validation is 96 passing tests. RT-019 and all six promoted M6
  assets remain passing. Details are in
  `evidence/sessions/20260712-mvp-quest-to-claim/live-continuation-20260713.md`.

## 2026-07-13 selected Daily-tab correction and retest

- The false-positive Main Quest/Daily Quest classification is corrected by `4f26889`: selected
  Daily recognition now requires the selected-tab state and an explicit Main Quest negative.
- The first live retest proved a separate target defect: the old broad tab ROI centered the tap at
  `(400,190)`, below the live tab label. The screen stayed Main Quest; the navigation-only record is
  retained as a no-effect unresolved navigation record, not an unresolved consequential action.
- `f3373f8` tightened the fixed-profile Daily-tab target to `(300,70,500,140)`, center `(400,105)`.
  A new journaled Quest→Daily action dispatched exactly one tap at `(400,105)` and positively
  confirmed the selected Daily Quest successor. No Daily Quest rows or objectives were inspected.
- Fresh retest evidence and schema-v1 database are retained in
  `evidence/sessions/20260712-mvp-quest-to-claim/live-selected-tab-retest-20260713/`. The full
  offline suite is 100 passing tests; RT-019 and all six M6 assets pass.
- Cleanup completed: game force-stopped, task worker removed, lease released, no task listener or
  tunnel remained, VM running, and RT-017 intact. The pre-existing ADB daemon was not killed or
  recreated.

## Current milestone and task state

- Milestones: M6 Production corpus — In Progress; M7 Deterministic service core — In Progress.
- Current task: MVP-QUEST-TO-CLAIM — Blocked after the 2026-07-13 live inventory selected the
  exact Help allies zero-cost R1 candidate but its first Alliance Help transaction remained
  unresolved after one dispatch. The action journal requires manual positive reconciliation before
  any later consequential input. No Claim row was present, no quest completion was proven, and no
  Claim input occurred. The typed navigation/task-module contracts remain local-ROI based; the
  AllianceHelpHandler is the first narrow supported handler. M6 and overall M7 remain In Progress.

- Independent later task: RT-016A — Pending; stable redacted account/server identity evidence is absent and remains required for M7-AccountGuard, not RT-013.
- RT-013 dependency: `RT-012 → RT-013`.
- Tasks completed in the preceding M5 run: M5-CUSTOM-BASELINE passed with 100 replay
  capture/classification operations, 25 target annotations, 10 OCR operations, ten gesture mocks,
  and five reconnect mocks; M5-AIRTEST and M5-MAA were rejected early with no live operations.
  M5-DECISION passed and authorized M6 corpus work. Earlier completed boundaries remain
  authoritative: RT-012, RT-013, RT-017, RT-019, RT-021, and MVP-STARTUP-NORMALIZATION.
- Tasks completed in this M6 boundary: M6-DQ-BOOTSTRAP passed. Fresh final-runtime Home/Base,
  Quest, and Daily Quest reconciliation frames, six profile-compatible assets, scroll overlap
  evidence, fail-closed synthetic fixtures, and cleanup evidence are retained. No Claim, Go,
  quest-completion, spend, or consequential gameplay input was recorded.
- Task completed in this repository-only M7 boundary: M7-SAFE-ACTION-CORE passed with no Unraid,
  VM, ADB, game, container, tunnel, or runtime-network access. Synthetic executor-success inputs
  were test-only and no production Claim-positive asset was created.
- Promotional escape review and live blocker evidence: `evidence/sessions/20260712-mvp-quest-to-claim/promotional-escape/`;
  the retained top-up frame passed the isolated arrow detector offline at similarity `0.898225`.
  The later bounded run sent one verified Back tap, reconciled Home/Base, then cancelled Home→Quest
  before dispatch on source change. No Claim-positive asset was created.
- Current MVP attempt evidence: `evidence/sessions/20260712-mvp-quest-to-claim/`. The schema-v1 task database
  has no nonterminal/unresolved action and its lease is released. The game is force-stopped, task
  worker/ADB/image removed, VM running, and RT-017 intact. The pre-existing loopback 5037 daemon
  was present initially but absent at final verification; no public listener exists.

## Repository state

- Branch: `main`.
- Latest completed implementation boundary: `1c87219`
  (`fix(tasks): use local Quest successor anchors`), following `e24b304` and `8483981`.
  The previous startup boundary was `d6fd1c7` (`fix(startup): accept bounded promotional successors`), following `5cec210`
  (`fix(startup): allow bounded verified promotional back`). The MVP closure remains task-scoped; the
  pre-existing unstaged entries remain untouched and no unrelated path is staged.
- Prior relevant policy/dependency commit: `7c932d2` (`docs(policy): remove risk acknowledgment gate`).
- The completed guarded keyguard branch, live-validation evidence, final Home/Base candidate, and
  passed task decision are included in the task-scoped closure boundary.
- RT-020 is removed from the committed backlog and plan; do not recreate it.
- Current dependency graph: `RT-012 → RT-013`; `RT-016A → M7-AccountGuard → later unattended automatic gameplay`; RT-014A is optional and does not delay RT-013.

## Runtime and rollback state

- VM: dedicated `PnS-BlissOS-PoC`, selected VirtIO(3D)/Mesa VirGL profile, running.
- Game: remains on the Alliance Help screen because the unresolved Help action evidence must be preserved; no further input is authorized.
- ADB: the task worker and its task ADB server were removed after evidence preservation; the approved pre-existing loopback daemon at 127.0.0.1:5037 was left untouched. No external tunnel or public/published listener remains.
  RT-021 direct worker proof used a temporary UID-65534 host-network container with an isolated
  local ADB server port; all RT-021 containers and that port were removed afterward.
- Observer: temporary container `rt012-observer-20260711-1519` and host collector completed and were removed/stopped after evidence preservation.
- Supervisor: completed normally at 2026-07-12 00:19:36 America/Chicago.
- VM autostart: disabled.
- Android startup state: resumed observe-only capture found the known safe launcher surface with
  `showing=false`, `secure=false`, and `mInputRestricted=false`. No additional keyguard swipe or
  HOME input was sent. The game reached Cash Mall, received exactly one authorized back-arrow tap,
  reached positively recognized Home/Base, and was force-stopped during cleanup.
- Read-only Unraid reconciliation on 2026-07-12 confirmed the VM is `running`, autostart is
  disabled, no RT-012/MVP/observer container or related process remains, the RT-017 backup
  directory/qcow2 remains present, and no temporary 5038/5040/5555 listener remains. The game is
  force-stopped during M6 cleanup. Fresh M6 reconciliation confirmed Android boot complete,
  logical `800x1280`, density 160, nonblocking keyguard, and the game activity foreground before
  cleanup. The exited M6 workers were inspected, their evidence preserved, and removed; only the
  pre-existing loopback ADB server on `127.0.0.1:5037` remained, with no external tunnel or
  published listener.
- Rollback: RT-001 baseline XML, disk identity, graphics rollback, and boot-state evidence remain retained; no disk replacement or destructive VM storage action occurred.

## Evidence

- RT-011: `evidence/sessions/20260711-rt-011-restart-matrix/` — passed restart matrix.
- RT-012 preflight and live evidence target: `evidence/sessions/20260711-rt-012-observe-soak/`.
- RT-012 prior blocker: `evidence/sessions/20260711-rt-012-soak-auth-block/record.md`.
- Live cache-backed evidence: `/mnt/cache/puzzle-survival-runtime/rt012/20260711-rt-012-observe-soak/`.
- RT-012 result: 48 valid, non-black `800x1280` frames; zero ADB failures; p95 capture 222.764 ms; 48 host metric files; 38,374,564 bytes under quota.
- Cash Mall reference: `evidence/sessions/20260711-rt-012-observe-soak/cash-mall-startup-reference.png`.
- RT-013 decision: `evidence/sessions/20260711-rt-013-runtime-decision/record.md`; preflight:
  `evidence/sessions/20260711-rt-013-runtime-decision/preflight.md`.
- RT-019 preflight: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/preflight.md`.
- RT-019 decision/evidence: `evidence/sessions/20260711-rt-019-runtime-profile-manifest/record.md`.
- Runtime profile: `runtime-profile/manifest.json`; profile ID
  `pns-blissos-poc-virgl-800x1280-v1`; canonical hash
  `195c145e5779b13d1f65708a6b3ef31f6cbdb934b33854f886f1091aa583d742`.
- RT-021 preflight: `evidence/sessions/20260711-rt-021-worker-vm-adb/preflight.md`.
- RT-021 decision/evidence: `evidence/sessions/20260711-rt-021-worker-vm-adb/record.md`.
- RT-017 preflight: `evidence/sessions/20260711-rt-017-runtime-backup/preflight.md`.
- RT-017 decision/evidence: `evidence/sessions/20260711-rt-017-runtime-backup/record.md`.
- Startup-normalization: `evidence/sessions/20260711-mvp-startup-normalization/record.md`; fresh
  worker cache copies are under `remote-cache/20260711-keyguard-reconcile-observe-2055/`,
  `remote-cache/20260711-cash-mall-observe-2120/`, and
  `remote-cache/20260711-cash-mall-input-2125/`.
- Resumed startup preflight: `evidence/sessions/20260711-mvp-startup-normalization/preflight-resume.md`.
- Resumed decision: `evidence/sessions/20260711-mvp-startup-normalization/record.md` final
  criterion review; Home/Base candidate manifest is
  `evidence/sessions/20260711-mvp-startup-normalization/home-base-candidate-manifest.json`.
- No RT-016A identity-evidence directory exists yet because its required manual identity exposure has not occurred.
- M5 custom baseline: `evidence/sessions/20260712-m5-custom-baseline/`; benchmark JSON records
  100 replay operations, 25 target annotations, 10 OCR calls, ten gesture mocks, five reconnect
  mocks, and the retained RT-010/RT-021 transport facts.
- M5 Airtest: `evidence/sessions/20260712-m5-airtest/`; early rejection records absent module/CLI,
  official dependency surface, missing central policy adapter, zero live operations, and the
  identical-corpus non-viability decision.
- M5 MaaFramework: `evidence/sessions/20260712-m5-maa/`; early rejection records absent
  native/package adapter, official native/pipeline surface, missing central policy adapter, zero
  live operations, and the identical-corpus non-viability decision.
- M5 final decision: `evidence/sessions/20260712-m5-decision/`; custom stack selected, rejected
  candidates compared, M6 authorized within scope, and no M6/Daily Quest work started.
- M6-DQ-BOOTSTRAP preflight and historical blocker: `evidence/sessions/20260712-m6-dq-bootstrap/preflight.md`.
- M6-DQ-BOOTSTRAP retained bootstrap captures, replay, and transport blocker:
  `evidence/sessions/20260712-m6-dq-bootstrap/`; final-runtime Daily Quest frames and
  `runtime-transport-blocker.md` are retained. The passed asset manifest, current reconciliation,
  scroll fingerprint, synthetic fixture results, and cleanup evidence are retained in the same
  directory.
- M7-SAFE-ACTION-CORE: `evidence/sessions/20260712-m7-safe-action-core/`; preflight, schema and
  lifecycle design, 44-test result, crash-boundary matrix, fixture review, and criterion decision
  are retained there.

## Blocker and required user action

1. `MVP-QUEST-TO-CLAIM` remains Blocked because the short Help All validation did not prove
   Daily Quest progress or produce a Claim row. The historical `alliance-help-20260713-001`
   tap at `(650,350)` was a proven-no-effect mistarget in the separate operational copy; its
   original journal remains immutable historical evidence.
2. No unresolved or nonterminal action remains in the reconciled operational journal, and no
   further consequential input is authorized until a fresh Daily Quest observation establishes
   current progress and an eligible objective or Claim row. Do not retry the historical tap.
3. Resume with the checked-in `scripts/pnsctl.py` interface, fresh runtime/profile reconciliation,
   and the existing single-objective MVP boundary. `M6-DQ-TRANSITION-CORPUS` remains downstream.
4. No credentials, login, tutorial, account switching, CAPTCHA, or profile navigation may be
   automated. RT-016A remains a separate later manual-only account-guard task.


## Facts that must not be re-tested

RT-001 through RT-013 are passed and their retained evidence is authoritative unless contradictory
evidence is discovered. Do not repeat the graphics, display, ADB-isolation, capture,
input-fidelity, restart-matrix, or four-hour observe-only experiments, and do not run RT-014A
concurrently with any live runtime task. RT-019 and RT-021 are also closed; do not rerun the
profile-validator or worker-path trials without contradictory evidence.

## 2026-07-14 Daily Quest scope and planning authority

- Current Daily Quest identity is `tasks/daily_quest_catalog.json`; current implementation,
  evidence, promotion, registration, persistence, and scheduler status is
  `tasks/daily_quest_execution_matrix.json`.
- Provenance audit invalidated prior 36-key claim. Catalog now contains 31 keys from the retained
  selected-Daily inventory record and raw-frame evidence. `tasks/daily_quest_provenance_audit.json`
  records exact wording, source paths, tab state, row-region availability, classification, and
  missing evidence for every disputed candidate.
- `Gather Food`/`Gathered Food` is `SYNTHETIC_ONLY`; Vehicle Depot, Ultimate Challenge, Hunt
  Zombie, and Own Hero are `PROVEN_MAIN_OBJECTIVE`; Headquarters attack/win is
  `DOCUMENTATION_ONLY`. None has a Daily catalog key, matrix owner, backlog owner, or prompt.
- Admission requires raw/lossless Bliss evidence or derived inventory, positive Quest screen,
  positive selected Daily tab, visible objective-list row, non-Main classification, and exact
  provenance. Prose, unknown-tab OCR, GnBots definitions, and synthetic fixtures do not admit
  objectives.
- Proven current statuses remain: Personal Might Praise live validated; exact Personal Might
  Daily Claim live validated support; individual Help and Help All live validated; canonical Help
  route `daily_go_to_speedup_help`. Existing operator registrations remain unchanged.
- Generalized Daily Claim, milestone Claim, Supply Depot, free Recruitment, persistence, and
  scheduler are offline contracts/infrastructure. No offline contract implies registration.
- Every matrix objective and support flow remains scheduler-ineligible. No worker, VM, ADB, lease,
  journal migration, live task-state row, evidence capture, or gameplay input is authorized in
  this planning run.

## 2026-07-14 Daily Quest prompt and planning validation

- Standalone prompts cover remaining dependency-ordered Daily Quest backlog tasks. The index is
  `docs/prompts/daily-quest/index.json`; prompt authority remains the execution matrix, and
  prompts are future implementation instructions rather than runtime authorization.
- `tests/test_daily_quest_planning.py` validates catalog-derived count/key parity, strict
  selected-Daily provenance admission/rejection, reconciliation coverage, matrix fields/enums,
  family ownership, backlog/prompt bijection, operator registration accuracy, Claim/milestone
  separation, Main Quest exclusion, and scheduler dormancy.
- Planning validator passes 11/11; focused catalog, planning, and retained-claim suites pass.
  Full discovery runs 240 tests with 8 known Windows/evidence-fixture errors: six evidence-hygiene
  errors from Python 3.9 `Path.stat(follow_symlinks=...)` or symlink privilege limitations, and
  two navigation errors from absent/unreadable retained images. No runtime state was changed to
  obtain these results.
