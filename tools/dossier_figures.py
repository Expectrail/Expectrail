"""Offline citation guard and exhaustive visible-figure diff for the release dossier."""
from collections import Counter
from html.parser import HTMLParser
import re


class Figures(HTMLParser):
    def __init__(self, text, local_sources=()):
        super().__init__(convert_charrefs=True)
        self.stack, self.missing, self.linked, self.records = [], [], [], []
        self.section = 'snapshot'
        self.local_sources = set(local_sources)
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h2':
            self.section = attrs.get('id', self.section)
        if tag not in {'meta', 'link', 'br', 'hr', 'img', 'input'}:
            self.stack.append((tag, attrs.get('href')))

    def handle_endtag(self, tag):
        for n in range(len(self.stack) - 1, -1, -1):
            if self.stack[n][0] == tag:
                del self.stack[n:]
                break

    def handle_data(self, text):
        if any(tag in {'style', 'script', 'svg'} for tag, _ in self.stack) or not re.search(r'\d', text):
            return
        href = next((url for tag, url in reversed(self.stack) if tag == 'a'), None)
        valid = href and (re.match(r'https://github\.com/Expectrail/Expectrail/(?:blob/|actions/runs/|issues/|commit/|tree/|pull/)', href)
                          or href in self.local_sources)
        (self.linked if valid else self.missing).append(text)
        self.records.append({'section': self.section, 'figure': text, 'source': href})


def changes(before, after, local_sources=()):
    """All changed visible numeric spans; source identities are metadata, not result figures.

    Do not pair unrelated additions/removals into an invented before/after measurement. Repeated
    occurrences retain their multiplicity. The JSON also retains full source identities separately.
    """
    old, new = Figures(before, local_sources), Figures(after, local_sources)
    def measured(row):
        text = row['figure'].strip()
        return not (re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}|#\d+|p(?:50|95)', text)
                    or re.fullmatch(r'(?:sources/|docs/|tests/|bench/|expectrail/).*', text))
    a = Counter((r['section'], r['figure']) for r in old.records if measured(r))
    b = Counter((r['section'], r['figure']) for r in new.records if measured(r))
    def rows(diff, records):
        return [{'section': section, 'figure': value, 'occurrences': count,
                 'sources': sorted({r['source'] for r in records if (r['section'], r['figure']) == (section, value) and r['source']})}
                for (section, value), count in sorted(diff.items())]
    return {'removed': rows(a-b, old.records), 'added': rows(b-a, new.records)}
