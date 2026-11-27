# Read a recorded sample result after a replay error (#249)

## What changed

`expectrail sample --json` writes the three sample results to standard
output. When the recorded profile runs the gate in the same process, its
replay warnings now go to standard error. The results keep their original
decisions and the command keeps its exit status.

## What was run

On November 23 I installed the [release rehearsal wheel](https://github.com/Expectrail/Expectrail/actions/runs/44983211397/artifacts/14739220883)
in an empty Debian 13 environment and ran the recorded sample with real
Godot and networking disabled. Xvfb was on the caller's path outside the
system directories mounted by the replay sandbox. The recorded sample
exited 3 and printed replay warnings before the array. A JSON reader failed
at line 1, column 1.

On main `de1ddd65`, a regression test using a stand-in runner that emits
the gate warning reproduced the same parse error. After the change,
`python3 -m unittest -v tests.test_wheel_sample` passed all eight tests.
The regression reads the full standard output with `json.loads`, finds
the warning on standard error and checks the needs-review row and exit 3.

I also built and installed the main and changed wheels offline, verifying
all 321 inputs of each against Git. With the same display setup failure,
both wheels exited 3 and reported needs-review for all three cases.
Main wrote five warnings to stdout. The changed wheel wrote all five to
stderr, and the complete stdout parsed as JSON.

With Xvfb at the standard system location, the published rehearsal wheel
ran in a clean Python 3.12.14 environment on Debian 13 using real Godot
4.7.2 and Mesa llvmpipe. The only network interface was loopback.

| Bundled sample profile | Doctor exit | Clean | Fall-through | Repaired | Sample exit |
| --- | ---: | --- | --- | --- | ---: |
| Default, no credentials | 3 | needs-review | reject | needs-review | 3 |
| Recorded vision | 0 | accept | reject | accept | 0 |

## Not done

The wheel came from the untagged rehearsal. A version-tag release remains
with Sean.

## Files

- `expectrail/cli.py`
- `tests/test_wheel_sample.py`
- `docs/new-work/2026-11-23-recorded-sample-json.md`
