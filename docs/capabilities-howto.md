# Update the capability ledger in your PR

Run `python3 -m expectrail.capabilities check` when the README or a public page
starts naming a command or another page. The check points to the source of an
unlisted mention and prints JSON for the ledger.

- For a supported mode, find its row in [the ledger](capabilities.json). Append
  the quoted module to that row's `entryPoints` array or the quoted page path to
  `docs`. The message suggests candidate row IDs based on the source page,
  module namespace, or an existing evidence link. Use the row that actually
  describes the capability. If the mode is new, add a row with its own evidence
  and limits.
- For a reference that describes no product mode, merge the printed JSON object
  into the indicated `notModes.commands` or `notModes.docs` map. Keep the existing
  entries and replace `<reason>` with a short explanation. For example, a guide
  for maintaining the ledger can use this fragment inside `notModes.docs`.

```json
{"docs/capabilities-howto.md": "explains how to maintain the capability ledger"}
```

Run `python3 -m expectrail.capabilities render`, then run `check` again. Include
the ledger JSON and its rendered page in the PR that introduces the reference.
