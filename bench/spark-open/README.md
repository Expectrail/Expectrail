# Muse Spark Open, live

Two runs of the **Spark Open** workflow on October 30, on public material only: the three approved
checks in `specs/` drafted again from their one-line instructions, the ground draft judged as
drafted on every seeded bug, and the team's scripted playtest sorted. Muse Spark on Meta's API drafted
the same checks in the same runs, for comparison. Each run's folder is written by
`python3 -m agents.spark_open collect --run <id>` from that run's annotations; this page is the index.

| Run | Spec prompt | Ground draft gives the approved spec's verdict, 9 seeded runs: Spark Open | Muse Spark | Folder |
| --- | --- | --- | --- | --- |
| [41026508747](https://github.com/seanudeke/Expectrail/actions/runs/41026508747) | `side` not defined | 3 of 9 (fails the clean game) | 9 of 9 | [`41026508747/`](41026508747) |
| [41027140573](https://github.com/seanudeke/Expectrail/actions/runs/41027140573) | `side` is where the object stays | **9 of 9** | 9 of 9 | [`41027140573/`](41027140573) |

**What served it.** `meta-models/muse-spark-open` on inference.baseten.co, 6 calls a run, no errors,
reported as served by that id. The key lists 20 models, and that is the only Muse or Spark one; the
id an earlier guide named (`meta-models/muse-spark-open-1026`) is not listed, so the code's default is
now the listed id.

**The first run, and the prompt change.** Spark Open's ground draft said the robot never crosses the
ground's top edge with side "below", so it failed the clean game and every seeded run. Muse Spark read
the same prompt as "above". The prompt listed the values of `side` but never said whether it is where
the object stays or where it must not go, so either reading fits it. It now says, with an example that
is not one of our checks (a ball under a ceiling). The 9 of 9 is after that change, and it is one run
at temperature 0: a fixed prompt, not a measured rate.

**What a person still fixes before approving.** All six drafts in each run are valid specs with the
approved assertion type, and none would be approved as drafted:

- The object prompts are generic: "player", "ground", "coin", where the approved specs say "blue
  robot", "grass-topped ground" and "gold coin". "ground" also matches the floating platforms. The
  model saw only the sentence, never the game (the same gap the first Muse Spark draft had,
  `bench/spec-writer-live/`).
- The ground tolerance is 8 px (12 in Muse Spark's first draft) against the approved 20, and the
  window is every frame against 0 to 119.
- The coins check names its object `coins` rather than `coin`.

**The playtest.** In both runs Spark Open sorted all 7 remarks into the same categories as the fixed
phrase rules wherever a rule applies, and flagged both requests to weaken a check itself. (The canned
offline answers miss the second one on purpose, so the rules have something to catch.) Both requests
went to the human queue. Of the two bug reports it drafted into checks, the floor check had the wrong
side in the first run and the right one in the second. The coin check ("coins only disappear when
touched") came back as a `reaches` assertion in both runs. That is not what the remark says, and the
honest answer was "unsupported". Neither check goes anywhere without a person's approval.

**Cost.** Spark Open used 3,963 tokens in and 7,424 out in the first run, and 4,246 and 6,335 in the
second. That is about 3 to 4 cents a run at $1.25 and $4.25 per million tokens (a third-party price
list, read October 30; Baseten's own page was not checked).

## Names updated on Nov 1

The project's earlier name was replaced with Expectrail in the format IDs in both `results.json` files. Nothing else
changed. The run wrote the earlier names; the files as recorded are at commit `85a5e253f635`.
