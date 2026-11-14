"""Local links, anchors and ledger references on the #266 front door; no network requests.

Only the named front-door documents and their direct link targets are inspected. Never crawl a
repository tree or follow private evidence links from the ledger. This is a link/advertisement
check, not proof that every prose claim is true; review claims against the linked row.
"""
from __future__ import annotations
import html
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
PAGES = ('README.md', 'docs/index.html', 'docs/quickstart.html', 'docs/concepts.html',
         'docs/guides.html', 'docs/positioning.html')
LEDGER = 'docs/capabilities.md'


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links, self.ids, self.steps = [], set(), []
        self.step = None
        self.feed(text)
        self.close()
        if self.step is not None:
            raise ValueError('unclosed quickstart command block')

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                raise ValueError('duplicate anchor: ' + attrs['id'])
            self.ids.add(attrs['id'])
        if tag in ('a', 'link') and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag in ('img', 'script') and attrs.get('src'):
            self.links.append(attrs['src'])
        if tag == 'pre' and 'data-quickstart-step' in attrs:
            if self.step is not None:
                raise ValueError('nested quickstart command block')
            self.step = {'name':attrs['data-quickstart-step'], 'exit':int(attrs['data-exit']), 'command':''}

    def handle_data(self, data):
        if self.step is not None:
            self.step['command'] += data

    def handle_endtag(self, tag):
        if tag == 'pre' and self.step is not None:
            self.steps.append(self.step)
            self.step = None


def anchors(path):
    text = path.read_text(encoding='utf-8')
    result = Page(text).ids
    if path.suffix == '.md':
        seen = {}
        for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$', text, re.M):
            heading = re.sub(r'<[^>]*>', '', heading).replace('`', '').lower()
            slug = re.sub(r'[^\w\- ]', '', heading).replace(' ', '-')
            n = seen.get(slug, 0);seen[slug] = n + 1
            result.add(slug + (f'-{n}' if n else ''))
    return result


def target(root, page, link):
    """Map this site's and this repo's public links to files, without requesting the URL."""
    parsed = urlparse(html.unescape(link))
    name = unquote(parsed.path)
    if parsed.netloc == 'github.com':
        prefix = '/Expectrail/Expectrail/'
        if name.rstrip('/') == prefix.rstrip('/'):
            name = 'README.md'
        elif name.startswith(prefix+'blob/main/'):
            name = name[len(prefix+'blob/main/'):]
        else:
            return None
        path = root / name
    elif parsed.netloc == 'expectrail.tech':
        path = root / 'docs' / name.lstrip('/')
    elif parsed.scheme or parsed.netloc:
        return None
    elif name.startswith('/'):
        path = root / 'docs' / name.lstrip('/')
    else:
        path = page.parent / name if name else page
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('link leaves checkout: ' + link)
    # A direct link may be checked for existence; never read private or fresh evidence as a target.
    if any(part.startswith('fresh-') or part == 'Expectrail-heldout' for part in path.parts):
        raise ValueError('front-door link asks for restricted evidence: ' + link)
    if path.is_dir():
        path = next((path/name for name in ('index.html','README.md') if (path/name).is_file()),path)
    return path, unquote(parsed.fragment)


def problems(root=ROOT):
    from expectrail import capabilities
    root = Path(root)
    out = []
    texts = {name:(root/name).read_text(encoding='utf-8') for name in PAGES}
    doc = capabilities.load(root/'docs/capabilities.json')
    # Include the new pages without weakening the existing README/site advertisement checker.
    out.extend(capabilities.advert_problems(doc,texts,root))
    row_ids = {row['id'] for row in doc['rows']}
    for name,text in texts.items():
        page = root/name
        try:
            links = Page(text).links
        except ValueError as exc:
            out.append(f'{name}: {exc}');continue
        if page.suffix == '.md':
            links += re.findall(r'\[[^\]]*\]\(([^\s)]+)\)',text)
        row_links = set()
        for link in links:
            try:
                found = target(root,page,link)
                if found is None:
                    continue
                destination,fragment = found
                if not destination.is_file():
                    out.append(f'{name}: missing target: {link}')
                elif fragment and fragment not in anchors(destination):
                    out.append(f'{name}: missing anchor: {link}')
                if destination == (root/LEDGER).resolve() and fragment in row_ids:
                    row_links.add(fragment)
            except (ValueError,OSError) as exc:
                out.append(f'{name}: {exc}')
        if not row_links:
            out.append(f'{name}: no capability-row link')
    return out


if __name__ == '__main__':
    found = problems()
    for message in found:print(message)
    print(f'Front-door links and ledger references: {len(found)} problem(s); no network requests.')
    raise SystemExit(bool(found))
