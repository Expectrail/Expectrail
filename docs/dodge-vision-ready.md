# Dodge's first vision run: preparation, not vision evidence (#263)

**Clipped-player follow-up:** [the edge comparison is now fixed and retested](dodge-clipped-player.md).
Both physical-body stand-ins accept clean pinned/harmless and reject broken; counts/cap are unchanged.
The original risk analysis below records the pre-fix result, not current observer behavior.

The full calibration → judge → recording → recorded replay path now runs with an explicitly
labelled **engine-box stand-in**, without a model or spend. It produces accept/reject/accept and
replays those same results. This proves plumbing only. **Dodge still has no live vision evidence.**
A second stand-in exposes a legal-edge size risk that Sean must review before spending; see below.
The [machine-readable counts and provenance](measurements/dodge-vision-readiness.json) are exact
for the saved local captures, not a forecast of SAM's answers or future renderer bytes.

## Exact question and cost plan

The route has 300 physics ticks at 60 Hz; capture is 60 fps, so each of the three variants has
300 frames, numbered 0–299: **900 PNGs captured, no model charge for capture**. The selected,
unchanged approved check is `dodge-play-area`, with `whenPlayerVisible` and at least 120 judged
frames. The real captures contain 183 visible frames on pinned/harmless (10–192) and 242 on
broken (10–251). No unknown lifecycle state occurs. The engine rejects broken at frame 97, so
the gate does not ask its point-based visual observer about that failed arm; it still performs
the existing paired-box comparison.

Calibration considers the original every-tenth frame plus the last (31 candidates), bounded by
`anchored.MAX_FRAMES = 64`. The conditional check's calibration uses only visible, fully interior
collision boxes: **10, 20, 30, 40, 50, 60, 70, 80, 90**. Frame numbers/PNG bytes are preserved;
hidden and clipped candidates are listed in the plan. Each selected frame has two **separate**
point requests, centre and nudge, never a two-point batch: **18 questions/images**.

| Phase on the complete, calibration-passing path | Logical point questions | Logical one-box questions | New requests/images after exact reuse |
| --- | ---: | ---: | ---: |
| Calibration centre + nudge | 18 | 0 | 18 |
| Pinned judgment | 183 | 0 | 150 |
| Broken judgment: head already fails in engine; base is checked again | 183 | 0 | 0 |
| Broken paired comparison: base 10–190 by 10; head 10–90 by 10 and 250 | 0 | 29 | 20 |
| Harmless judgment: head + base | 366 | 0 | 0 |
| Harmless paired comparison: both sides 10–190 by 10 | 0 | 38 | 0 |
| **Total** | **750** | **67** | **188** |

These 817 logical questions reuse only a successful answer to the identical PNG SHA-256,
question kind and exact point/box prompt, within this one job. Model/provider are fixed for that
client. A different image, point or box is another question. Errors are not cached; a hidden
frame is not sent and no fictitious model answer is recorded for it. The 188 submissions contain
160 distinct PNG hashes; sending one image with different prompts is billed as another image.
The complete point phases touch all 183 in-play frames on each nonfailing arm; the plan JSON
lists frame IDs per phase and all distinct request-key digests. The actual stand-in client made
exactly those 188 calls, and its recording answers all 188 on replay, with zero missing answers.

The repository records **$2.50 per 1,000 images** (`agents.sam_observations.USD_PER_IMAGE`):

| Bound for these exact captures | Requests / submitted images | List-price reservation |
| --- | ---: | ---: |
| No retries, full calibrated path | 188 / 188 | **$0.4700** |
| Every question succeeds on its fourth attempt (default three retries) | 752 / 752 | **$1.8800** |
| Workflow hard cap | at most 800 paid attempts; the next is refused before transport | **$2.00** |

Successful-answer `images` in the client's spend counter counts responses, while `requests` and
reserved USD include retries. All submissions above are priced as images, including point and
box prompts; this is the repo's list-price accounting. **Actual model requests and spend here: 0.**
The unchanged main path before this patch made 887 stand-in calls on the same full positive
control, equivalent to $2.2175, above the workflow's $2 maximum. Scope selection removes 70
non-exercised questions; exact reuse removes 629 further repeats. Calibration failure or a
provider stop asks fewer questions and never establishes an accept.

The live judge recomputes its exact plan from its incoming captures **before the first question**,
prints it, and appends it to `calibration.md`, which the existing workflow uploads. Different
renderer bytes can change reuse counts. $0.4700/$1.8800 are this capture's counts, not guaranteed
CI counts; the $2 cap remains binding. A fresh plan is also available without a client:

```bash
python3 -m tools.outside_vision_plan --project dodge-the-creeps \
  --data CAPTURES --digest CAPTURE_SHA256 --out request-plan.json
```

## Geometry, coverage and the remaining edge risk

The pinned scene's capsule has radius 27 and height 68: half-size **27 × 34**, full box 54 × 68.
The sprite is scaled 0.5; its four source frames become 53.5–55.5 px wide and 60–67.5 px high,
within the fixed calibration tolerance. The centre and a 3 px horizontal nudge are inside the
collision box (3 < 27). All four source textures have opaque centre/nudged pixels. This establishes
usable geometric points, not that SAM will identify the intended player. Calibration asks where
to look; it does not send the engine's box size to the model.

The positive stand-in returns the **engine observer's** player box, using its existing feet-offset
convention. It is deliberately tautological. A second stand-in returns the **physical collision
box clipped to the PNG**, approximating the geometry of a bounded visible mask. Both calibrate
9/9 against the unchanged `RULES`. But the clipped control rejects pinned and harmless at the
legal edges: **99 of 183 in-play frames, first frame 94**, are size-mismatch/not-drawn evidence.
The engine still passes pinned. The same clipped-control result replays from its own recording.
This is a stand-in stress finding, **not a measured SAM false-alarm rate**.

Only 84 in-play frames are fully interior; silently dropping clipped frames would also miss the
approved minimum of 120. The patch does neither that nor any change to the approved check or
`RULES`. Live SAM may answer differently; the first live run is a measurement. A demonstrated
accept needs actual visual answers on the approved window. Sean must decide whether to make
that measurement now or first coordinate an edge-aware observer change with the owner of PR
#493. Changing the spec/window needs a person's review and a new content-bound approval; a
rules change is Sean's decision. Neither is performed here. Do not use stand-in accepts as Dodge
vision evidence, and do not install their recording in the production recording bank.

## What is checked before a paid question

All variants' archive layout, route binding, schemas, frame/trace hashes, contiguous clocks,
complete 300-frame window, input actions and pinned Godot/OpenGL3 provenance are checked before
calibration. Mixed rendering environments, unknown/inadequate in-play coverage, fewer than eight
eligible calibration samples or an unusable/unapproved selected check stop with a plain reason.
Explicit custom observers can still produce the gate's ordinary needs-review records for an
unexercised check; the strict calibration eligibility applies when this path constructs the
anchored observer. No assertion or approval was changed.

The workflow already offers `dodge-the-creeps` and passes the project choice to both jobs. It
already selects Dodge's approved bounds check on current main, rather than the kinematic ground
check. The generic production observer uses the actual physics clock, so Dodge is one tick per
frame, not kinematic-character's two. The new dry-run client does the same. There is no use of
kinematic-character's calibration or recording for Dodge.

Capture uses Godot 4.7.2, software OpenGL3 and the normal sandbox, as CI does. The existing outside
vision and outside trial jobs both run Ubuntu 24.04. Our local captures report **llvmpipe LLVM
19.1.7**; the original recorded kinematic CI environment reports **LLVM 20.1.2**. Exact CI driver/
PNG identity is **not established** here. #515 already shows two pixels can differ across those
profiles, defeating exact lookup. A Dodge live recording uses its own incoming frames and records
their actual environment. Replaying those same files works in the stand-in proof; a later CI
recapture may still be `not-recorded`. No tolerance, renderer override or live fallback is added.

## Reproduce the stand-in only

```bash
python3 -m tools.outside_vision_dry_run --project dodge-the-creeps \
  --data CAPTURES --digest CAPTURE_SHA256 --out NEW_FOLDER
```

Add `--clip-to-frame` for the separate clipped-collision stress. No key or cap is needed: no model
client is constructed. Output directories, providers, recording model/run, summary and human
reports say **STAND-IN / NOT VISION EVIDENCE**. Unit tests use the same real engine vectors with
synthetic PNGs whose hash-alias relationships match the captures; they are not screenshots.

## Sean's single live step (not performed here)

**After this patch reaches main and after reviewing the edge risk**, in Actions → **Outside
vision** → Run workflow, select branch `main`, project **`dodge-the-creeps`**, cap **`2.00`**.
Equivalent command, for Sean only:

```bash
gh workflow run outside-vision.yml --repo Expectrail/Expectrail --ref main \
  -f project=dodge-the-creeps -f sam_usd_cap=2.00
```

The existing protected `main-only` environment must already make `MODEL_API_KEY` available to
that workflow. The input becomes `EXPECTRAIL_SAM_USD_CAP=2.00`. No workflow, setting, secret or
approval was changed here. Capture has no key; the judge reads saved data and uses no game code.

“Calibration passed” means the existing reader accepts `calibration.json` with `enabled: true`,
at least eight asked frames, found ≥90% of asked, size ≥90% of found within max(25%, 4 px), and
stable ≥90% of found. The second answer must still hold the first point, move less than half
the actual nudge (here <1.5 frame pixels), and match size within max(25%, 3 px). On these nine
samples, **all nine must satisfy each test**: 8/9 rounds to 0.889, below 0.9. Passing calibration
alone is not an accept. Keep the actual calibration, verdicts, spend, recording, capture digest
and run URL. Reject/needs-review is a result to report, not permission to loosen a rule.
