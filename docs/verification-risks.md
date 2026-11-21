# Verification risks

An Expectrail accept covers the approved obligations exercised on the named routes with the
required observations. A declared fix also needs a witness that the old build failed and the new
build passed. Defects outside those obligations can go unnoticed. Missing or ambiguous required
evidence leads to needs-review unless a concrete failure already warrants rejection.
[Decision rule](../expectrail/gate/record.py) · [Exercised coverage](exercised-coverage.md)

This register tracks *What can a game replay prove?*, the November 19, 2026 research review.
The review examined [c24fe36](https://github.com/Expectrail/Expectrail/tree/c24fe36a2590566b626a252beea349817a83fe7b).
Expectrail's code and ledger below were checked at
[f50b839](https://github.com/Expectrail/Expectrail/tree/f50b8390942e4468d4758d5ed7fa57304c8a697d)
on November 20. Closure criteria are proposed evidence for a named support profile. Q1–Q7 refer to
[the public evaluation questions](https://github.com/Expectrail/Expectrail/issues/282).

## 1. The route or check misses the bug

A route can finish without exercising the behavior, and a frozen actor can satisfy a check.
Just et al. compare detection of mutants and real faults. UTBoost's authors demonstrate erroneous
repairs passing insufficient tests.
[Mutation study](https://homes.cs.washington.edu/~rjust/publ/mutants_real_faults_fse_2014.pdf) ·
[UTBoost](https://aclanthology.org/2025.acl-long.189/)

**Today.** The gate checks route extent, required frames and coverage. A declared fix requires three
old failures and three new passes on a repair witness. JIT validity uses clean, near-miss and
subject-specific do-nothing controls. The harmless edit and mirror studies are advisory. This cycle
reproduced **0 of 137 counting** by re-auditing the frozen public records offline.
[Coverage](exercised-coverage.md) · [Intent](../expectrail/gate/intent.py) ·
[JIT rules](jit.md#generated-checks-that-count-271) · [Public audit](measurements/271-public-counting.md) ·
[Do-nothing](measurements/675-do-nothing-control.md) · [Harmless edit](measurements/675-harmless-control.md) ·
[Mirror study](measurements/675-metamorphic-mirror.md)

The hand audit requested in #686 is already in main. Freezing the player interrupted the physics
update that determines floor contact, so some apparent passes depended on the control's floor
state rather than the behavior under test. The control now leaves those cases indeterminate when
the two floor-state readings disagree.
[Hand audit](measurements/675-do-nothing-control.md#hand-check-of-a-sample-requested-on-686) ·
[Control code](../expectrail/jit/do_nothing.py)

Fresh replays of the frozen checks confirmed all five predicted losses. Their 29 historical
strong catches passed the do-nothing control and were dropped. A sixth case, gun-cooldown,
retained four strong catches. [Replay measurement](measurements/285-frozen-proposal-replays.md)

**Closure evidence (Q1–Q3, Q7).** Freeze checks and routes before a game owner independently labels
paired wrong and correct repairs, harmless edits and disabled behavior. Publish all three verdict
counts, missing triggers and counterexamples by family. Repeat the public reproduction audit under
the current validity rule. [Control change #686](https://github.com/Expectrail/Expectrail/pull/686) ·
[Reproduction #285](https://github.com/Expectrail/Expectrail/issues/285) ·
[Counting #271](https://github.com/Expectrail/Expectrail/issues/271)

## 2. Replay flake and runner drift

Input delivery, simulation state, rendered images and verdicts can each diverge. Godot Movie Maker
controls capture time. Factorio's engineers describe separate simulation reproducibility tests and
desync diagnosis. Google's flake figures describe its own test fleet.
[Godot manual](https://docs.godotengine.org/en/4.7/tutorials/animation/creating_movies.html) ·
[Godot maintainer discussion](https://github.com/godotengine/godot-docs/issues/5202) ·
[Factorio](https://www.factorio.com/blog/post/fff-55) ·
[Google test fleet](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)

**Today.** The Godot harness pins the engine, input steps and seed, records rendering provenance and
compares frames and traces. The ledger cites a twice-rendered Linux smoke run. Unity's experimental
lane has its own cross-runner comparison. The macOS issue records suite and process lifecycle
failures. A paired cross-OS trace and PNG comparison remains outstanding.
[Harness](harness.md) · [Comparison runner](../harness/replay_check.py) ·
[Godot evidence](capabilities.md#godot-harness) · [Unity evidence](capabilities.md#unity-harness) ·
[macOS #378](https://github.com/Expectrail/Expectrail/issues/378)

**Closure evidence (Q6).** Replay public pairs three times per named runner, with cold and warm
starts. Report input, trace, PNG and verdict agreement separately, first divergent tick or frame,
and engine, OS, CPU and renderer. A supported host profile needs its own stable decisions. A
per-property divergence budget needs fresh public evidence that it preserves protected failures.

The Unity and browser lanes need separate replay boundaries. PhysX documents ordering and
platform conditions. Box2D and Rapier document specific choices and constraints for deterministic
simulation. Playwright documents screenshot dependence on the host environment.
[PhysX](https://nvidia-omniverse.github.io/PhysX/physx/5.1.3/docs/BestPractices.html) ·
[Box2D](https://box2d.org/posts/2024/08/determinism/) ·
[Rapier](https://rapier.rs/docs/user_guides/rust/determinism/) ·
[Playwright](https://playwright.dev/docs/test-snapshots)

## 3. Clock, identity and coordinate errors

Measuring the right value about the wrong entity or tick can clear the wrong change. Fixed physics
steps and still frames sample at different boundaries. Physical timestamps need device-specific
calibration. [Godot Movie Maker](https://docs.godotengine.org/en/4.7/tutorials/animation/creating_movies.html) ·
[Stb-tester timestamp experiment](https://stb-tester.com/blog/2016/07/05/latency-measurements)

**Today.** New captures bind frames to tick intervals, phase, viewport, transform and PNG digest.
The gate validates the map and refuses required gaps. Singular targets can need review on ambiguous
identity. Class-level visibility can be satisfied by any member. Events between draws can be
unobserved. [Timeline](observation-timeline.md) · [Validator](../expectrail/observation_timeline.py) ·
[Evaluator](../expectrail/evaluator.py)

**Closure evidence (Q1, Q3, Q4).** Shift streams, change capture rates, move the camera, resize the
viewport, spawn an entity between draws and cross or occlude look-alike sprites. Independently label
objects and instants. Require review for missing or ambiguous observations and rejection for a
known visible violation. [Timeline #257](https://github.com/Expectrail/Expectrail/issues/257)

## 4. Renderer differences and tolerance

A renderer change can make an exact recording unusable. Allowing small global pixel differences
can also hide a property the check protects. Chromium and Web Platform Tests provide
comparison parameters for individual reference tests.
[Skia Gold matcher](https://chromium.googlesource.com/chromium/src/%2B/refs/tags/121.0.6117.1/ui/base/test/skia_gold_matching_algorithm.h) ·
[Web Platform Tests](https://web-platform-tests.org/writing-tests/reftests.html#fuzzy-matching)

**Today.** Lookup requires the exact PNG digest, question kind and prompt. Capture provenance can
explain some misses. The saved drift fixture and a sparse player recolor overlap on changed-pixel
count and maximum channel difference. The capture comparison associates the change with different
renderer profiles. It cannot isolate the driver as the cause.
[Lookup](../expectrail/recorded.py) · [Reproduction](recorded-renderer.md) ·
[Renderer #515](https://github.com/Expectrail/Expectrail/issues/515)

**Closure evidence (Q2–Q4, Q6).** Measure unchanged, hidden, moved, resized and small recolor controls
on fresh routes across pinned profiles. Publish answer coverage and wrong verdicts by check. A
bounded policy would require independent validation of protected regions and object identities.
Missing required answers continue to need review.

## 5. Vision and telemetry share an error

An engine-provided anchor gives the game influence over what the observer sees. Pixel segmentation
can identify the wrong object. Glitch recognition and sprite identity are different evaluation
tasks. [SAM 3](https://github.com/facebookresearch/sam3) ·
[VideoGameQA-Bench](https://arxiv.org/html/2505.15952v1)

**Today.** The anchor starts at the engine box. The historical outside run rejected an invisible
sprite but reported a misleading boundary reason. Recorded and stand-in calibration work checks
ambiguity and shape. Kinematic-character is the only outside project with live vision in the
ledger. [Anchor](../expectrail/anchored.py) · [Calibration](observer-calibration.md) ·
[Outside run](outside-projects.md#first-outside-game-verified-with-vision-november-14-2026) ·
[Ledger](capabilities.md#outside-projects)

**Closure evidence (Q2–Q5).** Compare engine-only, anchored and independently located vision on the
same fresh cases. Include wrong engine coordinates, swapped identities, matching scenery,
occlusion and harmless tint. Score identity, geometry, reason, verdict and unanswered requests.
Show a labeled pixel counterexample on a second outside title and tag its observation cost.

## 6. Adaptive pressure compromises the evaluation

Repeated exposure to cases and detailed judgments can teach check or patch authors to satisfy the
available tests. NASA's IV&V guidance distinguishes technical, managerial and financial
independence. [UTBoost](https://aclanthology.org/2025.acl-long.189/) ·
[Anthropic's coding study](https://www.anthropic.com/research/emergent-misalignment-reward-hacking) ·
[NASA IV&V](https://www.nasa.gov/ivv-overview/)

**Today.** Approval binds to spec content. The CI judge pins the base policy, and JIT can withhold
the candidate from the proposer. Historical held-out evaluation and the public two-job workflow
have different exposure rules. Base-side judgment cannot supply missing intent or checks.
[Approval](capabilities.md#spec-writer) · [CI policy](ci-gate.md) · [Candidate withholding](jit.md#what-runs)

**Closure evidence (Q1, Q5, Q7).** Seal independent labels and freeze the judge, policy and evidence
budget before evaluation. Publish only aggregate blind results and separate exposed development
results. Compare engine-only, hybrid, strong screenshot and ordinary studio checks on identical
eligible pairs with disclosed inputs and costs.

## 7. Needs-review resolves too little for the cost

Abstention can be right and still leave QA repeating the test. The outside vision run and
AltTester's assisted integration case give examples of observation and setup expense in specific
settings. [Public vision run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623) ·
[AltTester case study](https://alttester.com/case-studies/implementing-a-reliable-and-scalable-game-test-automation-solution-on-real-mobile-devices/)

**Today.** Missing vision, coverage or approvals can force review despite useful findings. The
spend caps bound model calls. Outside trials record machine time and known stops. The cost of
resolving reviews on customers' changes remains unmeasured.
[Outside results](outside-projects.md) · [Spend caps](spend-caps.md) · [First-user kit](first-user-test.md)

**Closure evidence (Q2, Q3, Q5).** Enroll consecutive outside submissions and record eligibility,
outages, abstentions and overrides. Record cause, reviewer time and final disposition. Compare
total cost and engineering time per correctly resolved change with ordinary retesting on the same
work. Ask the team to set its own cost of errors and delays.

## 8. Setup, consent and art changes prevent repeat use

Telemetry requires a compatible build, bindings and permission to instrument it. Art changes can
make an existing template ambiguous or unusable. AltTester describes assisted integration. Side
and modl.ai describe difficulties integrating source-based testing and announce a pilot.
[AltTester proof of concept](https://alttester.com/case-studies/implementing-a-reliable-and-scalable-game-test-automation-solution-on-real-mobile-devices/) ·
[Side and modl.ai](https://side.inc/news/side-and-modl-ai-sign-memorandum-of-understanding)

**Today.** The installed lane accepts a compatible Godot project with configured routes and
approved checks. The outside reports preserve setup stops. The frozen template bank was tested on
an untuned route and calibration refused different art. Machine time on prepared projects leaves
unaided developer setup time open.
[Installed command](capabilities.md#installed-command) · [Outside trials](outside-projects.md) ·
[Template transfer](template-sensor-untuned-summary.md)

**Closure evidence (Q3, Q5).** Observe consenting developers following public instructions on
their own projects. Time a useful first verdict and a second change after an art or engine
update. Record staff help, unsupported scenes and who approves intent. Test evidence export and
redaction with the project owner before retaining recordings.

## 9. Playback substitutes for executing the changed code

Playback of recorded presentation or replicated state describes an old execution. Unreal uses
replicated data to reconstruct a replay, and rr and TTD inspect recorded executions.
[Unreal replay](https://dev.epicgames.com/documentation/en-us/unreal-engine/using-the-replay-system-in-unreal-engine) ·
[rr paper](https://www.usenix.org/conference/atc17/technical-sessions/presentation/ocallahan) ·
[Microsoft TTD](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-overview)

**Today.** The declared-fix gate requests fresh base and head replays. The split CI reader checks
the bundle against replay and game-tree identities. Recorded vision answers questions about
matching PNGs from current capture. It supplies no substitute state or frame.
[Gate](../expectrail/gate/verify.py) · [Bundle reader](../tools/ci_bundle.py) ·
[Recorded vision](recorded-renderer.md)

**Closure evidence (Q1, Q6).** Use a public case where only fresh execution of the change exposes
the difference. Show that both builds ran and that the judge refuses a stale base bundle
presented as candidate evidence. Execution binding still leaves capture authenticity to prove.

## 10. Capture is inside the game's trust boundary

A contained process can produce misleading output. A physical sensor also has boundaries:
signal format, color conversion, timestamps, missing frames and inaccessible intervals.
Magewell documents unsupported inputs. Stb-tester measures timestamp error for specific devices.
[Magewell diagnostics](https://magewell.com/kb/detail/000050048/All) ·
[Stb-tester calibration](https://stb-tester.com/blog/2016/07/05/latency-measurements)

**Today.** Bubblewrap limits access on supported Linux runs. The game writes its own frames and
trace. The ledger distinguishes diagnostic runs from isolated signed judging and protected
capture. The two-job publisher and receipt reader have fixture evidence. There is no independently
calibrated physical-capture lane.
[Sandbox](replay-sandbox.md) · [Capture grade](capabilities.md#godot-harness) ·
[CI grade](capabilities.md#ci-head-clearance) · [Receipts](capabilities.md#verifier-receipts)

**Closure evidence (Q1, Q4–Q6).** Compare candidate-written frames and traces with an independently
owned capture of behavior. Bind that capture to a named build and policy in a deployed signed judge
and verify it offline. A physical lane needs authorized access, tagged timing and color controls,
a calibrated latency budget and explicit handling of inaccessible or dropped intervals.
[Capture #246](https://github.com/Expectrail/Expectrail/issues/246) ·
[Deployment #254](https://github.com/Expectrail/Expectrail/issues/254)

## 11. Reproducible evidence preserves a wrong answer

A cache can reliably return a mistaken observation. Signatures bind the evidence bytes and source
claims. The semantics of the observation still depend on the sensor and ground truth.
[SLSA provenance](https://slsa.dev/spec/v1.2/build-provenance) ·
[Sigstore verification](https://docs.sigstore.dev/cosign/verifying/verify/) ·
[SAM 3](https://github.com/facebookresearch/sam3)

**Today.** Observation records carry source digest and observer version, with entity identity
where supplied. The recorded observer distinguishes missing answers from an answered absence.
The historical hidden-sprite result illustrates why the verdict and its reason warrant separate
audit. [Observation contract](observation-timeline.md#observation-contract-and-identity) ·
[Recorded observer](../expectrail/recorded.py) · [Outside example](outside-projects.md#first-outside-game-verified-with-vision-november-14-2026)

**Closure evidence (Q2, Q4, Q6).** Sample fresh and saved answers and hide their origin from
independent annotators. Compare target identity and condition labels against raw frames and
required events. Verify that a stale or misidentified answer cannot satisfy a current required
claim even when its digest and signature verify.

## 12. Substitutes and maintenance cost erase the advantage

Quickscope documents replay inputs, screenshots and state. Meticulous documents recorded user
interactions for change comparison. RethinkDB's founder describes the company's business
shutdown. These sources establish substitutes and named outcomes. A paid market for independently
judging game repairs remains unverified.
[Quickscope](https://regressiongg.beehiiv.com/p/quickscope) · [Meticulous](https://meticulous.ai/how-it-works) ·
[RethinkDB](https://rethinkdb.com/blog/rethinkdb-shutdown/?mode=reply)

**Today.** Local replay, check formats and a fixture-tested receipt reader are in the repository.
The public evidence centers on pinned Linux Godot. Unity and browser work has narrower diagnostic
scope. Wider GPU and console claims need their own supported profiles.
[Installed command](capabilities.md#installed-command) · [Receipt reader](capabilities.md#verifier-receipts) ·
[Unity](capabilities.md#unity-harness) · [Browser](capabilities.md#web-checkout)

**Closure evidence (Q3–Q5).** Compare ordinary retesting and a buyer-selected substitute on the
same repair pairs. Observe a second independent use and paid renewal. For each new platform,
measure accuracy, stability, cost and portability on a named build and capture profile. Show that
exported evidence and its reader work offline after a service or engine version changes.

## Comparing the review with the ledger

- The ledger's generated-checks row says there is no promotion path. Its wording predates the
  opt-in authenticated counting path in code and offline tests. Ordinary summaries remain
  advisory, the reproduced public audit yielded zero counting, and approval remains a human
  decision. A counting pixel failure can veto. A repair witness needs an eligible approved or
  trace check, and clearance needs an approved check to run.
  [Ledger](capabilities.md#generated-checks) · [Counting rules](jit.md#generated-checks-that-count-271) ·
  [#600](https://github.com/Expectrail/Expectrail/issues/600) · [#638](https://github.com/Expectrail/Expectrail/issues/638)
- The review quotes historical hybrid and engine-only results tied to specific cohorts and code.
  The current head-clearance row cites fixture evidence. Its hosted qualification remains open.
  The judge benchmark also reports strong screenshot-only comparators on the same development
  cases.
  [CI ledger](capabilities.md#ci-head-clearance) · [Judge benchmark](evaluation.md#who-accepts-a-fix-that-only-looks-right-judge-benchmark)
- The review and ledger identify one outside live-vision project. The November 20 comparison adds
  a recorded-vision repair witness on that same project. The job saved its decisions before
  failing a rehearsal assertion. The run leaves independent onboarding, a second live-vision
  title and trusted clearance open.
  [Outside ledger](capabilities.md#outside-projects) · [November 20 comparison](outside-projects.md#four-repairs-on-kinematic-character-november-20-2026)
- The renderer record establishes a pixel difference across two saved profiles. Cause attribution
  to LLVM alone remains unverified. The receipt reader is implemented and fixture-tested. Trusted
  issuance remains undemonstrated.
  [Recorded vision ledger](capabilities.md#recorded-vision) · [Receipt ledger](capabilities.md#verifier-receipts)
- **Unverified from primary evidence.** VMware's version 6 manual documents replay. Version 8
  removal is reported in a dissertation, and the reason remains unverified. Unity's announcement
  establishes the launch of a separate Game Simulation offering. Its terminal outcome, customer
  results and reason for any termination remain unverified. Unity's package manual describes
  Automated QA recordings. The separate pause notice was inaccessible during this check.
  [VMware manual](https://ist.mit.edu/sites/default/files/migration/products/vmware/ws6-manual.pdf) ·
  [Dissertation](https://collections.lib.utah.edu/dl_files/ae/fa/aefaef43372138879e63470cea4d51292894bb6e.pdf) ·
  [Unity launch](https://unity.com/news/unity-releases-cloud-based-simulation-solution-help-game-creators-achieve) ·
  [Automated QA manual](https://docs.unity3d.com/Packages/com.unity.automated-testing@0.8/manual/index.html) ·
  [Unity forum notice](https://discussions.unity.com/t/automated-qa-development-on-hold/865190)
