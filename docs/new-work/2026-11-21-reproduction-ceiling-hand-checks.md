# Measure the hand-written reproduction ceiling (#762)

## What changed

Recorded the English obligations and the frozen first proposal for slow-left, slides-after-stop
and air-jump. The three case folders provide source-only replay commands and supporting
measurement artifacts. The report distinguishes results that use stock probes, author-supplied
probe programs and manual combinations of advisory predicates.

## What was run

- Pinned Godot 4.7.2 on `d5b1e8f`. The three jobs completed 156 formal probe replays across clean,
  defect, frozen player and comment-only arms. Each arm was repeated three times. The report
  names the control outcome and clean clearance for each applicable check.
- The stock-library left-travel floor met the expected outcomes in all four arms. The wider
  sliding and air-jump diagnostics did so with bounded author-supplied probes. The exact jump-count
  conjunction passed by hand and the proposal parser refused the compound operation.
- Checked the original frozen hashes and clean scope of the three case runners. No proposal
  used its optional revision.
- Cross-checked all 156 results, verified 13 relative documentation links and passed the
  documentation evidence budget. Fetched the required historic commit. The full
  `python3 -m unittest discover -s tests -t .` suite reported 5,946 tests, 84 skipped and zero
  failures.

## Not done

These are local advisory diagnostics without Bubblewrap isolation. Live model generation,
stock reproduction scoring, and production approval are outside this measurement. The excluded
patrol report needs the developer's answer to the question recorded in the measurement.

## Files

- [Measurement and conclusion](../measurements/762-reproduction-ceiling-hand-checks.md)
- [Slow-left case](../../bench/jit/ceiling/762/slow-left/README.md)
- [Slides-after-stop proposal](../../bench/jit/ceiling/762/slides-after-stop/jit-proposal.json)
- [Air-jump case](../../bench/jit/ceiling/762/air-jump/README.md)
- This work-log entry.
