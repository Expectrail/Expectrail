# Renew the controlled fixer's seven-day price review (#267)

## What changed

The model's price review expired on November 23. Full discovery on #813 passed
on a Linux host whose local date was still November 23. Both required GitHub
jobs ran on November 24 UTC and stopped in the repair-kit tests.
[Hosted test](https://github.com/Expectrail/Expectrail/actions/runs/45329895450/job/138228309281) · [Hosted package job](https://github.com/Expectrail/Expectrail/actions/runs/45329895450/job/138228309792)

I checked the public pricing table, model page, deprecations table, prompt
caching guide and Chat Completions reference on November 24. The default cache
write, long-context rates, regional premium and full input-context ceiling give
$5.842584 for the controlled request with 4,096 output tokens. The capability
record's two review dates now cover November 24 through December 11. The run
sheet gives the next review date. [Sources](../live-repair/price-provenance.txt)

## What was run

`TZ=UTC` reproduced one failure and six errors in the two affected modules on
`a4a72c95`. On the refreshed record, the two modules ran under UTC with `python3 -m unittest -v tests.test_live_repair_kit tests.test_repair_live_case`. The 20 tests had three
optional skips and zero failures. The default plan reported a $10 envelope and
zero paid calls. I also set the date in an isolated check of the production
planner and sender against the tests' loopback server. On December 11 the plan
succeeded and admission made one metadata GET. On December 12 the plan refused
the expired price, and admission stopped before any HTTP request.

Sean set the window to December 11 on November 25, one day past the December 10
submission, so the next forced review falls after the deadline rather than
inside the final week. The November 24 review is unchanged and the rates are
unchanged; only the window moved. The reserve already stands at $5.50 input and
$16.50 output per million against base rates of $2 and $10, so a price move
inside 2.75x input or 1.65x output stays covered by the existing quote.

## Not done

This was a public tariff review. Live availability and billed usage remain
unmeasured. The next review needs new public source evidence.

## Files

- `contracts/examples/provider-capabilities/openai.json`
- `docs/live-repair/price-provenance.txt`
- `docs/live-repair/RUN-SHEET.md`
- `docs/new-work/2026-11-24-fixer-price-review.md`
