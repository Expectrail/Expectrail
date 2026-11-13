# Missing tools are reported before integration tests run

## What changed

The fixer's Bubblewrap probe now asks for the same PID and network namespaces as
an offline or gateway call. It reports the refusal once and keeps the existing
Docker or no-sandbox fallback. The probe and real call share the namespace options.
The replay probe in `harness/sandbox.py` already uses its real command builder,
including `--unshare-net`; that file is unchanged. A regression test checks both.

The drawn event and pause replays, gateway socket tests, Bubblewrap guard tests,
and browser replay/fix tests check their prerequisites. Missing tools skip with
the tool and reason unless their required switch is set, in which case they fail.
The browser preflight handles missing installation pieces only. Other browser
errors propagate. Existing assertions are unchanged.

CI now requires AF_UNIX sockets in both full-suite jobs and Chromium in the web
adapter step. The existing required engine and Bubblewrap switches remain in place.

## What was run

- `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`: exit 0.
- Before, `python3 -m unittest discover -s tests -t .`: 3,055 tests;
  8 failures, 9 errors, 25 skips.
- Test first, `python3 -m unittest tests.test_missing_tools -v`: 9 tests;
  5 failures and 4 errors before the implementation. The namespace comparison
  failed because the probe omitted `--unshare-net`.
- `python3 -m unittest tests.test_missing_tools tests.test_event_input tests.test_pause_input tests.test_gateway tests.test_guard tests.test_web -v`:
  66 tests, OK, 15 skips naming missing prerequisites.
- The same affected integration modules with `EXPECTRAIL_ENGINE_TESTS=required`,
  `EXPECTRAIL_GATEWAY_TESTS=required`, `EXPECTRAIL_REQUIRE_BWRAP=1` and
  `EXPECTRAIL_WEB_TESTS=required`: 57 tests, 11 failures, 4 errors, zero skips.
  This is the deliberate negative control: required tools cannot silently skip.
- After, `python3 -m unittest discover -s tests -t .`: 3,059 tests;
  1 failure, zero errors, 38 skips. The only failure is
  `tests.test_runit_edge.EdgeFunctionTest.test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract`.
  Sean excluded it because PR #412 fixes the Node reporter separately. That file
  is unchanged. Exact-name comparison excluding only that test: 16 before, zero
  after, no new failures/errors. Class prerequisite skips change unittest's
  reported test count; no test was deleted.
- The real Bubblewrap probe now reports the NETLINK_ROUTE permission denial;
  two detections choose `none` and print one warning. An explicit Bubblewrap
  call still exits 1 with that denial, as expected on this machine.
- AST comparison of assertion calls in the five edited existing test modules:
  every existing assertion call is unchanged.

## Not done

No successful real xvfb, AF_UNIX, network-isolated Bubblewrap or Chromium run
was possible here. CI was not run. The architect must validate the required
integration tests on Linux with those prerequisites available. The full local
suite does not end in OK because of the explicitly excluded Node failure.
No change to the replay sandbox, Node test, vision, app, job store or games.
No commit, push or GitHub write was made.

## Files

- `agents/sandbox.py`
- `.github/workflows/ci.yml`
- `tests/tool_requirements.py`
- `tests/test_missing_tools.py`
- `tests/test_event_input.py`
- `tests/test_pause_input.py`
- `tests/test_gateway.py`
- `tests/test_guard.py`
- `tests/test_web.py`
- `docs/new-work/2026-11-13-skip-missing-tools.md`

## Architect run (Linux, main c5d1e533; Godot, xvfb-run, AF_UNIX and Chromium present, no Bubblewrap)
Full suite: 3094 tests, OK, 27 skipped, the same skips as main: nothing newly skipped on a machine that has the tools. Required runs: `EXPECTRAIL_ENGINE_TESTS=required EXPECTRAIL_GATEWAY_TESTS=required` on test_missing_tools, test_event_input, test_pause_input, test_gateway: 37 OK; `EXPECTRAIL_WEB_TESTS=required` test_web: 21 OK. The Bubblewrap guard tests are proven only by CI's agents-sandbox job.
