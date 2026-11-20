# Shared styles for the hub and local app

The canonical asset is [expectrail.css](expectrail.css). The hub can link it as a static stylesheet. The local app can bundle those same bytes and insert them in its existing nonce-bearing style element to keep local verification offline. The stylesheet uses system fonts and has no imports or asset requests.

| Selector | Use |
| --- | --- |
| `main`, `h1`, `h2` | Page width, page title and section headings. |
| `section` or `.panel` | A panel. Prefer a labelled section when it has a heading. |
| `.grid` | Two equal columns, stacked at widths up to 600px. |
| `.note` | Secondary information, for example the date and source of a recording. |
| `label`, `input`, `select` | Native form controls and their labels. |
| `button`, `.button`, `.secondary` | Use a button for an action or an anchor with class `button` for navigation. Add `secondary` for a lower-priority action. For an unavailable action use a native disabled button and visible explanatory text. |
| `.result`, `.details`, `.error`, `.folders` | Result summary, multiline diagnostic, error text and a definition list of folder paths. The original app IDs are supported. Pair `error` with `details` when line breaks matter. |
| `.verdict` | Add `data-verdict="accept"`, `"reject"` or `"needs-review"` to a recorded verdict. Include the verdict in visible text. |
| `[hidden]`, `summary` | Native hidden and expandable states. Links, buttons, inputs, selects and summaries receive a visible focus ring. |

The `--er-*` properties on `:root` define type, spacing and colour. The existing local app still embeds its original CSS. Its consumer change belongs to builder two.
