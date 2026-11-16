"""Open every page of the site in a real browser and fail on anything broken.

    python3 -m agents.check_pages docs              # CI: every .html page under docs/
    python3 -m agents.check_pages docs --offline    # a machine without internet (see below)

For each page, served over HTTP from the folder (as GitHub Pages serves it), it reports:
- a script error: an uncaught exception, including a syntax error that stops a whole script;
- a file the page asks for that the folder does not have (a frame, a video, a stylesheet);
- a relative link to a file or folder that does not exist (a review page, a README);
- on a page with a <select> (the demo's case picker), an error raised while switching to each option.

A syntax error in one inline script leaves the page looking fine until someone uses it, which is how
a broken demo page passed CI before: nothing opened it.

--offline is for machines that cannot reach the page's CDN (Tailwind). It blocks every request that
is not to the local server and defines an empty ``window.tailwind`` so the page's own setup line still
runs. CI runs online, without it.

Exit 1 when anything is found. Findings name the page and what failed; they never print page text.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

SETTLE_MS = 1500
OPTION_MS = 150


def pages(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.html") if ".git" not in p.parts)


def _serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401 - keep CI logs to findings
            pass

    handler = functools.partial(Quiet, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _local_target(root: Path, page: Path, href: str) -> Path | None:
    """The file a relative link points to, or None when it is not a local link."""
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc or href.startswith(("#", "mailto:", "javascript:", "data:")) or not parsed.path:
        return None
    path = unquote(parsed.path)
    return (root / path.lstrip("/")) if path.startswith("/") else (page.parent / path)


def _landed(root: Path, base: str, url: str) -> Path | None:
    """The local file a page's final URL serves, after any redirect."""
    if not url.startswith(base):
        return None
    path = unquote(urlparse(url).path).lstrip("/")
    return root / (path + "index.html" if path == "" or path.endswith("/") else path)


def _exists(target: Path) -> bool:
    return target.is_file() or (target.is_dir() and any((target / n).is_file() for n in ("index.html", "README.md")))


def check(root: Path, *, offline: bool = False, browser=None) -> list[dict]:
    """Findings: {page, what, detail}. Starts its own browser unless one is passed in."""
    from playwright.sync_api import sync_playwright

    root = root.resolve()
    server, base = _serve(root)
    findings: list[dict] = []
    manager = None
    try:
        if browser is None:
            manager = sync_playwright().start()
            browser = manager.chromium.launch()
        for path in pages(root):
            rel = path.relative_to(root).as_posix()
            url = urljoin(base, rel)
            context = browser.new_context()
            page = context.new_page()
            errors: list[str] = []
            missing: set[str] = set()
            page.on("pageerror", lambda exc, errors=errors: errors.append(" ".join(str(exc).split())[:200]))

            def on_response(response, missing=missing):
                if response.url.startswith(base) and response.status >= 400:
                    missing.add(response.url[len(base):])

            page.on("response", on_response)
            if offline:
                page.add_init_script("window.tailwind = window.tailwind || {};")
                page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base)
                           else route.abort())
            page.goto(url, wait_until="load")
            page.wait_for_timeout(SETTLE_MS)
            for select in page.query_selector_all("select"):
                for value in select.eval_on_selector_all("option", "opts => opts.map(o => o.value)"):
                    select.select_option(value)
                    page.wait_for_timeout(OPTION_MS)
            hrefs = page.eval_on_selector_all("a[href]", "as => as.map(a => a.getAttribute('href'))")
            landed = _landed(root, base, page.url) or path  # a page that redirects (docs/index.html) links from where it lands
            context.close()

            for message in dict.fromkeys(errors):
                findings.append({"page": rel, "what": "script error", "detail": message})
            for asset in sorted(missing):
                findings.append({"page": rel, "what": "missing file", "detail": asset})
            for href in sorted(set(hrefs)):
                target = _local_target(root, landed, href)
                if target is not None and not _exists(target):
                    findings.append({"page": rel, "what": "broken link", "detail": href})
    finally:
        if manager is not None:
            browser.close()
            manager.stop()
        server.shutdown()
        server.server_close()
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", type=Path, help="the site's folder, e.g. docs")
    p.add_argument("--offline", action="store_true", help="block the CDN and stub Tailwind (no internet here)")
    args = p.parse_args(argv)
    found = check(args.root, offline=args.offline)
    for f in found:
        print(f"::error title=Page check::{f['page']}: {f['what']}: {f['detail']}")
    n = len(pages(args.root))
    print(f"::notice title=Page check::{n} pages opened in Chromium: {len(found)} problem(s)"
          + (" (offline: CDN blocked)" if args.offline else ""))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
