# A schema's pattern matches as JSON Schema means it; a non-string adapter is a config error (#251)

## What changed
Two edges the merge guard found in its review of #367 (both on #251):
- `expectrail.gate.record.schema_pattern`: the contract validator compiled a schema's `pattern` as a
  Python regex, where `$` also matches before a final newline, so `"godot\n"` passed `^[a-z]...$`
  in a findings record and in a verify request. Every `$` outside a character class and not
  escaped now becomes `\Z`, and patterns compile with `re.ASCII` (in a schema `\d` is an ASCII
  digit). One place, so every reader of every contract gets it.
- `expectrail.gate.verify.adapter_for` raised `TypeError` for an adapter that is not a string or
  an adapter (`run_gate(adapter=["godot"])`); it is now `ConfigError`, and nothing is replayed.

## What was run
- `python3 -m unittest tests.test_schema_pattern`: 6 tests, OK.
- The full suite on the branch: see the pull request.

## Not done
Nothing else on these two points. #251's remaining items are listed on the issue.

## Files
- `expectrail/gate/record.py`, `expectrail/gate/verify.py`
- `tests/test_schema_pattern.py` (new)
- `docs/new-work/2026-11-13-schema-pattern-end.md` (this file)
