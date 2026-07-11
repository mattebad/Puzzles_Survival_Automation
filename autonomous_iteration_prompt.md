Use Plan Mode only. Do not implement code yet.

I want to explore and plan a local personal-use automation project for a mobile game. The goal is to understand the best way to build a maintainable automation loop that uses ordinary UI interaction only: screenshots, OCR, computer vision, accessibility/UI automation if available, taps, swipes, waits, and safe recovery.

Do not prematurely lock into a specific architecture, framework, folder structure, CLI design, data model, or library stack. Research and compare options first, then recommend the best path forward.

The eventual automation should be able to:

* open/login to the game
* identify the current screen/state
* close routine popups
* complete simple daily quest paths where feasible
* claim obvious completed daily rewards
* join zombie lairs/rallies when stamina/resources allow
* run campaign levels when AP/resources allow
* send gathering marches when march slots are available
* perform certain low-risk daily resource/cooldown interactions
* return to a safe home/base screen after each task
* stop safely when uncertain

Hard constraints:

* Use only normal UI interaction and local observation/control.
* Reliability, observability, and maintainability matter more than speed.
* Every action that spends resources, materials, premium currency, stamina, AP, march slots, or time should be explicitly classified by risk.
* For every task, distinguish between:

  * detect/report only
  * dry-run only
  * execute automatically
  * execute only with explicit allowlist/spend-limit configuration
  * defer/manual-confirm only
* The bot should stop or require confirmation when the current screen, selected target, resource cost, or consequence is uncertain.

Deployment requirements:

* Preferred target is running from my Unraid NAS.
* Development can be performed on a macOS or Windows PC for local iteration, testing, and tooling, even if the final runtime target is Unraid or another server environment.

- Preferred runtime would be Docker if technically feasible.
- If Docker is not reliable for this game, evaluate fallback options:

  * Unraid VM running Windows + BlueStacks
  * Unraid VM running another Android emulator
  * Linux-native Android emulator/container approach
  * physical Android device controlled over ADB
  * separate mini PC running BlueStacks
- Explicitly evaluate whether BlueStacks is viable from Unraid directly, whether it likely requires a Windows VM, and whether Docker-based Android emulation is realistic for this use case.
- Consider operational concerns: headless operation, ADB access, graphics acceleration, KVM/GPU requirements, Google Play support, game compatibility, persistent storage, logging, recovery, remote monitoring, and how to observe/control the game if the automation gets stuck.

Available screenshots and domain context:
I will provide screenshots of:

* the Daily Quest list
* home/base screen
* base/building radial menus
* Nova/Bioenhancer screens
* Gear Factory/Nanoweapon screens
* Commander Info / Gear / Chip / Module enhancement flow
* additional task-specific screens as needed

Use these screenshots as planning/domain context, not as final implementation assets. The actual automation should still include a discovery/validation process before executing actions. Also note that some screenshots may be from iPhone; final computer-vision templates should be captured from the actual runtime target, such as BlueStacks, Android emulator, Docker Android container, at the same resolution/DPI/scaling used in production.

Known UI context from screenshots:

* The home/base screen has stable bottom navigation including World, Hero, Quest, Bag, Mail, Alliance, and More.
* The top-left player/commander icon opens Commander Info.
* Resource/stamina/AP indicators appear near the top/left of the home screen.
* The Daily Quest screen has tabs such as Main Quest, Daily Quest, and Alliance Activity.
* Daily Quest rows show either Claim or Go.
* Daily Quest milestone crates appear at 30/60/90/120/150 points.
* The Daily Quest screen shows current Daily Quest Pts and reset time.
* Some game features are reached through bottom navigation.
* Some features are reached by tapping buildings on the base screen and selecting radial-menu options.
* Building radial menus may show options like Details, Upgrade, Nova, Bioenhancer, and Research.
* Red-dot indicators are common and should not be treated as sufficient proof of the correct action by themselves.

Known gameplay loop, subject to validation:

* Login/open game and recover to base/home screen.
* Close routine popups.
* Open Daily Quest list.
* Claim completed quest rows and milestone crates where available.
* Perform repeatable low-risk routine actions.
* Spend stamina through zombie lairs/rallies if safe.
* Spend AP through Campaign if safe.
* Send idle marches to gather Food, Wood, Steel, and Gas if march slots are available.
* Perform selected daily shop, alliance, training, free research, supply, enhancement, and crafting actions only when safe and allowlisted.
* Return to home/base after each task.
* Stop if the UI state is unknown.

Daily quest categories and candidate flows:

1. Claim-only daily quest tasks

* Some quests are already complete and show a Claim button.
* The bot should eventually identify completed rows and claim them.
* It may also claim milestone chests when daily quest points reach 30/60/90/120/150.
* This is likely a strong first MVP because it is low-risk and contained mostly within the Daily Quest screen.
* Candidate flow:
  home/base → Quest → Daily Quest → detect visible Claim buttons → tap/claim → scroll → repeat → claim milestone crates if available → return home.

2. Training tasks
   Known quests:

* Train Fighter x250
* Train Rider x250
* Train Shooter x250
* Train Vehicle x250

Desired behavior:

* Train only the minimum required quantity for the daily quest where possible.
* Desired troop choices:

  * Fighter: max tier if appropriate, minimum quest quantity.
  * Rider/Shooter/Vehicle: likely T1/minimum-cost units for daily completion.
* This spends resources and should require clear guardrails, detection, and configured behavior.
* Do not blindly start large troop batches.

3. Stamina / Zombie Lair tasks
   Known quests:

* Consume 20 stamina.
* Defeat Zombie Lair 1x.

Gameplay notes:

* Stamina is consumed by joining or sending a march to a zombie lair/rally.
* Zombie lairs can be joined from the home screen when rally/lair notifications appear, or through a manual lair search/join flow.
* The UI may show right-side rally/lair notification icons with timers.
* There may be a quick-join path and a manual-join path.
* For manual joining, the bot may need to tap a lair, choose join, select a single troop/march, and confirm.
* Important rule: do not join level 60 lairs. Those are used by other players for stamina-building behavior and should be excluded.
* If the bot cannot confidently read or detect the lair level, it should not join.
* If stamina, march availability, or lair level is uncertain, stop or require confirmation.

Candidate flow:
home/base or world/rally notification → detect lair/rally availability → verify stamina available → verify lair level is allowed and not level 60 → verify march slot available → join/confirm with minimal safe march → return home.

4. AP / Campaign tasks
   Known quests:

* Consume 20 AP.
* Ultimate Challenge / Join Ultimate Challenge 1x may also be reachable through Campaign.

Gameplay notes:

* AP is used in Campaign.
* Campaign can be completed by selecting a campaign level and using Blitz/sweep if available, or by challenging the stage.
* If challenging manually, battle has waves and may require tapping auto-battle/endgame arrow.
* Preferred plan should evaluate whether Blitz/sweep is safer than active battle automation.
* Ultimate Challenge may count after entering/initiating and exiting once.

Candidate flow:
home/base → Campaign → choose safe repeatable campaign level → Blitz/sweep if available, otherwise evaluate challenge automation → confirm AP use → return home.

5. Gathering / resource-node tasks
   Known quests:

* Gather Food x30000.
* Gather Wood x30000.
* Gather Steel x6000.
* Gather Gas x1500.

Gameplay notes:

* Gathering requires going to the world map, using search/magnifying-glass UI, finding the correct resource node type, avoiding occupied/already-targeted nodes, and sending a march.
* Must account for march slot availability.
* Should avoid overriding existing marches.
* This is core but non-trivial due to map navigation, search result handling, march state, and occupied-node detection.

Candidate flow:
home/base → World → Search → select resource type → find node → verify node available/not occupied/not already targeted → send march → confirm → repeat by resource type if slots available → return home.

6. Shop / purchase tasks
   Known quests:

* Make purchase in Ruins Shop.
* Make purchase in Rare Earth Shop.
* Make purchase in Alliance Shop.
* Possibly Mystery Shop-related paths.

Gameplay notes:

* Alliance Shop is under Alliance → Alliance Shop.
* Ruins/Rare Earth shops may be reachable from Mystery Shop or related store screens.
* Candidate purchases may include cheap/safe daily items such as chip enhance material or module enhance material, subject to validation.
* Must avoid accidental premium-currency or expensive purchases unless explicitly allowlisted.
* The plan should propose an allowlist-based purchase strategy.

Candidate flow:
navigate to shop → detect affordable allowlisted item → verify currency/cost → buy exactly one → confirm → return.

7. Alliance tasks
   Known quests:

* Help allies 10x.
* Donate for alliance tech 10x.
* Make one Alliance Shop purchase.

Gameplay notes:

* Help allies may appear as a hand icon on the bottom UI when helps are available.
* Alliance tech donations require using configured resources and available donation attempts.
* Donations may refresh over time.
* Must avoid high-value spending unless allowlisted.

Candidate flow for helps:
home/base → detect help hand icon → tap help → confirm helps counted if visible → return.

Candidate flow for tech:
home/base → Alliance → Tech → choose configured safe tech/donation target → donate available safe amount → stop at configured cap → return.

8. Supply Depot tasks
   Known quest:

* Get supplies 5x at Supply Depot.

Gameplay notes:

* Supply Depot usually has multiple free resource claims per day.
* Candidate behavior: navigate to Supply Depot, claim available free supplies, stop when no free claim is visible.
* Must avoid spending currency if free claims are exhausted.

9. Challenge/entry tasks
   Known quests:

* Join Ultimate Challenge 1x.
* Enter Ruins Challenge 1x.

Gameplay notes:

* Often entering/challenging once and exiting counts.
* Candidate behavior: enter the screen, initiate the minimum required action, exit safely.
* Should avoid spending premium resources or running complex combat unless required and validated.

10. Nova / Praise / Bioenhancer tasks
    Known quests/interactions:

* Bioenhancer Research x1.
* Nova Praise / Nova points may be claimable from Nova.
* Some daily activity may involve tapping Nova, then a red-dot Nova/Praise path.
* Praise appears to have cooldown/attempt behavior.
* Bioenhancer Research appears to provide one free research action per day or cooldown cycle.

Gameplay notes:

* On the base screen, tapping the Research Lab/building may open a radial menu with options like Details, Upgrade, Nova, Bioenhancer, and Research.
* Nova screen has daily interaction options such as Affinity, Praise, and Gift.
* Nova Praise may have a red-dot indicator and an interaction attempts/cooldown system.
* Bioenhancer Research has a “Research 1x” and “Research 10x” style UI and may show whether a free research is available.

Desired behavior:

* Navigate to Nova.
* Perform or claim available Praise interactions when safe.
* Respect cooldowns.
* Avoid spending premium resources unless explicitly allowlisted.
* Navigate to Bioenhancer Research.
* Perform only free research when available.
* Avoid consuming paid research items or premium currency unless allowlisted.
* Record cooldown if free research is unavailable.
* Treat Nova/Bioenhancer as a separate task family because it has cooldowns, red-dot indicators, and potential paid actions.

11. Resource item and speedup tasks
    Known quests:

* Use resource item x1.
* Speed up 180 minutes using items.

Gameplay notes:

* Resource item can be done through Bag → resources/speedups → use one resource item.
* Speedups can be done by applying speedups to an existing build/research/training/etc.
* Must avoid wasting valuable speedups or diamonds.
* Prefer allowlisted item types, maximum spend limits, and safe task targets.
* If no safe speedup target exists, report/skip.

12. Commander Gear / Chip / Module enhancement tasks
    Known quests:

* Enhance gear 1x.
* Enhance chip 1x.
* Enhance module 1x.

Known candidate flow:

* Tap the player/commander icon in the top-left area of the home/base UI.
* This opens Commander Info.
* Commander Info has tabs such as Gear, Chip, Module, Cube, and Bioenhancer.
* For Gear:

  * Open Gear tab.
  * Tap one equipped gear item.
  * A stats modal opens with actions such as Enhance, Promote, Modify, Replace, and Unequip.
  * Tap Enhance only.
  * On Enhance Gear screen, select exactly one 1★ Gear Enhance Material.
  * If a quantity modal opens, ensure quantity is exactly 1, then tap Use.
  * Confirm the enhancement.
* For Chip:

  * Open Chip tab.
  * Tap one equipped chip.
  * Use the same pattern: Enhance only, select exactly one 1★ material, quantity 1, confirm.
* For Module:

  * Open Module tab.
  * Tap one equipped module.
  * Use the same pattern: Enhance only, select exactly one 1★ material, quantity 1, confirm.

Strict safety rules for Commander enhancement:

* Never tap Auto Select.
* Never select 2★, 3★, 4★, 5★, or higher materials.
* Never tap Promote, Modify, Replace, Unequip, Inherit, or any non-Enhance action.
* Never enable filters such as showing higher-star materials unless the plan can justify why it is safe.
* Never spend premium currency.
* Never proceed if the bot cannot confidently identify:

  * current tab: Gear, Chip, or Module
  * selected item type
  * Enhance button
  * 1★ material
  * quantity set to exactly 1
  * Confirm button
* If the available 1★ material count is zero or unreadable, skip the task and report it.
* Treat this as a resource-sensitive task requiring allowlist/configuration, screenshots/templates, and dry-run validation before execution.
* Model Gear/Chip/Module enhancement as one reusable task pattern with category-specific detection targets, rather than three unrelated hardcoded scripts.

13. Gear Factory / Nanoweapon tasks
    Known quests/interactions:

* Craft Nanoweapon 1x.
* Nanoweapon material production may also be relevant.

Gameplay notes:

* Gear Factory screen contains multiple feature areas: Gear, Chip, Module, Nanoweapon, Cube, and Amplify.
* Nanoweapon has tabs such as Craft Weapon, Material Production, Nanoweapon, and Inherit Weapon.
* Crafting a Nanoweapon appears to consume materials and may start a long build/craft process, around 12 hours.
* Nanoweapon material production has a Produce button and produces random materials.
* Desired behavior:

  * distinguish between Craft Weapon and Material Production
  * detect whether crafting/production is available
  * avoid consuming scarce materials unless the task is explicitly allowlisted
  * avoid starting expensive or long-running production unless configured
  * respect existing craft/build timers
* Treat Nanoweapon actions as resource-sensitive and not part of the first low-risk MVP unless the plan justifies it.

14. Upgrade hero / hero-related tasks
    Known quest:

* Upgrade hero 3x.

Gameplay notes:

* This may be done from hero/player-related screens.
* It may spend hero materials.
* Needs careful target selection and spend limits.
* Should likely be resource-sensitive and deferred until navigation/detection are reliable.

15. Building and PvP tasks
    Known quests:

* Upgrade building 1x.
* Join Hero Duel 3x.

Gameplay notes:

* Building upgrades can have strategic implications and may consume significant resources/build queues.
* Hero Duel may require lineup changes or more complex PvP screen handling.
* These should likely be deferred, detected/reported, or require manual confirmation in early versions.

Planning requirements:

* Do not assume every daily quest should be automated in version one.
* Produce a preliminary daily-quest automation catalog.
* For each known quest/category, classify:

  * candidate flow
  * preconditions
  * required detection targets
  * required screenshots/templates/OCR targets
  * resource/spend risk
  * stop conditions
  * whether it is claim-only, navigational, resource-spending, combat, map/march-based, cooldown-driven, or complex
  * whether it should be automated immediately, dry-run only, execute only with allowlist/spend limits, require human confirmation, or be deferred
  * recommended MVP phase
* The plan should recommend the smallest useful MVP from this quest taxonomy.
* Prefer low-risk repeatable actions first, then expand into stamina/AP/gathering/resource-sensitive actions once navigation and recovery are reliable.

Architecture exploration:
Research and compare viable approaches. Consider, but do not prematurely choose:

* Python + ADB + OpenCV/uiautomator2
* Airtest
* Appium
* scrcpy or high-speed capture + OpenCV + ADB input
* OCR-assisted workflows
* Android Accessibility / MediaProjection-style approaches
* Dockerized Android emulator/container approaches
* BlueStacks in Windows VM
* hybrid approaches

For each approach, evaluate:

* implementation complexity
* reliability for a game-rendered UI
* maintainability
* debugging experience
* portability across emulator/device
* screenshot/capture quality
* input-control reliability
* headless/remote operation feasibility
* suitability for Cursor-driven development
* likely failure modes
* fit for Unraid/Docker/VM deployment

Comparable projects/repositories/frameworks:
Research public docs and public GitHub repos if available. Look for comparable projects involving:

* Android game automation
* OpenCV/template matching
* ADB-driven input
* Airtest game automation
* mobile game bots using screen-scraping/OCR/task scheduling
* base-builder automation loops
* Android emulator in Docker
* Android automation from a NAS/server context

Potential examples to consider include:

* airtestproject/airtest
* uiautomator2
* Appium
* docker-android / Android emulator container approaches
* open-source Android game automation repos using OpenCV/ADB/OCR
* any stronger examples you find

For each relevant repo/framework, summarize:

* what it does
* what stack it uses
* what architectural ideas are reusable
* what should not be copied
* whether it is a suitable base, reference, or discard

Game-loop discovery strategy:
Propose how to safely map the game UI before building real automation:

* screen/state inventory
* screenshots/templates needed
* OCR targets
* task-flow recording
* screen transition mapping
* popup handling
* resource detection for stamina/AP/march slots/material counts
* store/shop cost detection
* lair level detection, especially to avoid level 60 lairs
* building radial-menu detection
* recovery paths back to home/base
* manual review checkpoints
* dry-run validation before live tapping
* ways to detect when the bot is unsure and stop cleanly

Subagent/discovery-agent design:
Evaluate whether a discovery subagent makes sense.

If yes, design a safe version:

* what it may observe
* what it may label
* what it may propose
* how it can cluster screens/states from screenshots
* how it can infer possible transitions
* what actions require human confirmation
* how to prevent random/destructive tapping
* how to convert observations into candidate task specs
* how to separate discovery from live execution

A discovery agent should generally observe, label, classify, and propose. It should not freely execute arbitrary taps in the live game. Any guided exploration should be constrained to allowlisted safe navigation actions and should stop on unknown states.

Recommended phased roadmap:
Produce a phased plan from exploration to MVP and beyond. The roadmap should include phases such as:

* research and comparable project review
* deployment feasibility proof-of-concept for Unraid/Docker/VM/BlueStacks/physical device
* device/capture proof-of-concept
* screenshot collection and screen/state discovery
* template/OCR evaluation
* navigation/recovery layer
* dry-run task planning
* first executable MVP task
* expansion to dailies/lairs/campaign/gathering
* expansion to resource-sensitive allowlisted tasks
* logging/testing/hardening
* remote monitoring and operations

Success criteria:
Define how we know each phase is complete. Include concrete validation steps such as:

* can reliably capture screenshots from the chosen runtime
* can detect home/base screen with confidence
* can detect Daily Quest screen with confidence
* can detect Claim buttons and distinguish Claim from Go
* can scroll Daily Quest list and avoid duplicate actions
* can return home from common screens
* can close known popups safely
* can dry-run a task path without tapping
* can execute one narrow low-risk task safely
* can stop on unknown states
* can save logs/screenshots on failure
* can run unattended for a bounded period without making unsafe decisions
* can report which tasks were completed, skipped, or require manual action

Expected output:
Produce a planning document with these sections, but do not be limited by them if a better structure emerges:

1. Executive recommendation
2. Deployment feasibility analysis for Unraid/Docker/VM/BlueStacks/physical-device options
3. Comparable project/repo/framework review
4. Architecture options and tradeoff table
5. Recommended architecture and rationale
6. Game screen/state model
7. Daily quest automation catalog
8. Discovery-agent/subagent design
9. Phased implementation roadmap
10. MVP definition
11. Testing and validation strategy
12. Logging/observability/remote monitoring strategy
13. Safety, spend-limit, and stop-condition strategy
14. Risks and mitigations
15. Open questions that must be answered before implementation

Autonomy:

* You may inspect the current workspace if one exists.
* You may inspect attached screenshots and derive candidate states/flows from them.
* You may research public docs and public GitHub repos if tools are available.
* You may propose architecture, tradeoffs, and implementation phases.
* Do not create files or write code until I approve the plan.
* If internet access, GitHub search, device access, or screenshot access is unavailable, state that clearly and produce the best plan from available context.
