# A schema's pattern matches as JSON Schema means it; a non-string adapter is a config error (#251)

## What changed
Two edges the merge guard found in its review of #367 (both on #251):
- `expectrail.gate.record.schema_pattern`: the contract validator compiled a schema's `pattern` as a
  Python regex, where `$` also matches before a final newline, so `"godot\n"` passed `^[a-z]...$`
  in a findings record and in a verify request. Every `$` outside a character class and not
  escaped now becomes `\Z`; `\d`, `\D`, `\w`, `\W` become ASCII classes, and `\s`/`\S` stay Unicode,
  as in ECMA-262. One place, so every reader of every contract gets it.
- After the merge guard's review of #375: the first version compiled with `re.ASCII`, which also
  made `\s` ASCII and so accepted values main refused (U+00A0 at the end of a capabilities field).
  `re.ASCII` is gone, and `schema_pattern` now returns a `SchemaPattern` that matches only when
  both the JSON Schema reading and Python's own reading match. So however the translation reads a
  pattern, the validator never accepts a value it refused before; where the two differ the
  stricter wins (a non-ASCII digit is refused by `\D`, which JSON Schema would take).
- `expectrail.gate.verify.adapter_for` raised `TypeError` for an adapter that is not a string or
  an adapter (`run_gate(adapter=["godot"])`); it is now `ConfigError`, and nothing is replayed.

## What was run
- `python3 -m unittest tests.test_schema_pattern`: 10 tests, OK. They include: every contract
  pattern has a matching sample, and that sample plus a newline is refused where anchored (and was
  taken by plain `re.search`); the capabilities field refuses U+00A0, U+2028, U+3000 at either
  end; for every contract pattern and a set of probe values, `schema_pattern` accepts nothing
  `re.search` refuses.
- The full suite on the branch: see the pull request.

## Not done
Nothing else on these two points. #251's remaining items are listed on the issue.

## Files
- `expectrail/gate/record.py`, `expectrail/gate/verify.py`
- `tests/test_schema_pattern.py` (new)
- `docs/new-work/2026-11-13-schema-pattern-end.md` (this file)
