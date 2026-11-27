# Keep the selected Run it result visible during a background run (#265)

## What changed

A visitor can open an earlier result while another run finishes. The reservation, progress and publication callbacks now retain the identity of the panel that started the run. Completion still updates that sample's card and makes the Run it buttons available again.

## What was run

I exercised the page JavaScript from main `de1ddd65` and the proposed change with a DOM stand-in, an in-memory service and two public status files. On main, starting the clean sample and then opening the earlier bug sample left the bug title above the clean request's accept. This happened both before and after reservation. The change kept the bug's reject visible in both orders and showed the completed clean run on its own card.

A quota refusal, a failed background run and a cancelled background run also preserved the selected bug's message with the change. All three overwrote it on main. Staying on the clean run showed its accept on both versions. No live run was started.

[Clean status](https://github.com/Expectrail/Expectrail/blob/f82a7127c80afef774f23a221acf9c5f3cc6a283/cc4d1b39-1529-4232-ae73-267bbd8c1574/status.json) · [Bug status](https://github.com/Expectrail/Expectrail/blob/f82a7127c80afef774f23a221acf9c5f3cc6a283/4f609d1c-fce8-4962-a31b-cee08924a832/status.json)

On main `35c961b2`, an additional check held the status file response after publication. A visitor who switched to the bug during that wait saw its correct rejection, but reopening clean loaded the old saved request. The page’s registered click handlers ran in V8 with a DOM stand-in, the committed earlier results and an in-memory new clean result. With the fix, the clean card showed the new time and reopened `new-clean-run` in all three switch orders. The browser regression now includes this timing and checks the reopened request ID.

## Not done

The Playwright regression, historic fetch, export scan and full discovery still need a working checkout. The DOM stand-in results above cover the candidate only. Sean owns signing and the fresh-visitor trial.

## Files

- `docs/run-it/run-it.js`
- `tests/test_runit_offline.py`
- `docs/new-work/2026-11-24-run-it-selected-result.md`
