# The section menu folds behind a Menu button on phones and tablets

## What changed

Sean asked for the top menu (Quickstart, Concepts, Guides, Positioning, Evidence ledger, Run it) to be a toggle,
especially on mobile, and on desktop if there is a clean way. Nielsen Norman Group's 179-person study found hidden
navigation hurts discoverability more on desktop than on phones, and recommends a visible "Menu" label beside the icon.
So desktop keeps its visible links, and the toggle appears at 860 px and below.

- `docs/assets/nav.js` (new):
  - reveals the button and marks the header `has-toggle`;
  - opens and closes the menu, updating `aria-expanded` and switching the label between "Menu" and "Close";
  - closes on Escape (focus returns to the button), on a link click, on a click outside, and when the window widens
    past 860 px;
  - marks the current page's link `aria-current="page"` at every width.
- `docs/assets/front-door.css`: the toggle (pill button, three bars that turn into an ×) and the open panel (full-width
  links, each at least 44 px tall), with a short fade-in that reduced motion turns off. The links hide only under
  `.has-toggle`, so without the script they are always shown.
- `docs/assets/home.css`: dark-theme colours for the open panel.
- The five front-door pages: the hidden button sits right before `<nav aria-label="Sections">`, and each page loads
  `nav.js` and `front-door.css` under a tag made from the file's SHA-256, like `home.css` since #530.
  Run it and Verify have three-link headers that already fit a phone, and are unchanged.
- `tests/test_site_nav.py` (new, 3 tests):
  - the button is on each page in front of the nav;
  - the stylesheet and script tags match the files;
  - the menu folds only once the script runs, and Escape and `aria-expanded` are handled.

## What was run

- Headless Chrome on all five pages at 390, 768, 1024 and 1440 px:
  - at 390 and 768 the links start hidden, the button opens them (`aria-expanded="true"`, label "Close", every link
    44 px or taller), Escape closes them with focus on the button, and a click outside closes them;
  - at 1024 and 1440 the button is hidden and the links show;
  - the current page is marked on the four inner pages;
  - no overflow and no script errors anywhere.

  With JavaScript off at 390, the links show and the button doesn't. Open-menu screenshots of the home page (dark)
  and Guides (light) at 390 were looked at.
- `python3 -m unittest discover -s tests -t .`: `Ran 4047 tests`, `OK (skipped=42)`.
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems. `python3 -m tools.front_door`: 0 problems.
  `python3 -m expectrail.capabilities check`: exit 0.
- The five-page front-door browser check (the architect's local script): 10 of 10, after teaching it to open the menu
  before clicking a link on a phone.

## Not done

- No desktop toggle, for the reason above.
- No sticky header: the header sits in its own wrapper, so it would need restructuring on every page.

## Files

- `docs/assets/nav.js`
- `docs/assets/front-door.css`
- `docs/assets/home.css`
- `docs/index.html`
- `docs/guides.html`
- `docs/concepts.html`
- `docs/positioning.html`
- `docs/quickstart.html`
- `tests/test_site_nav.py`
- `docs/new-work/2026-11-15-site-menu-toggle.md`
