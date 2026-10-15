"""Check visible bilingual HTML against hash-bound formal MDX declarations.

The scheduled check samples each locale across the complete sorted inventory,
and includes every disabled page. It is explicitly not a full-page attestation.
Acceptance may request the complete inventory. Hydration JSON and scripts cannot
substitute for the request declaration that readers actually see.
"""
import concurrent.futures
import hashlib
import html
from html.parser import HTMLParser
import io
import re
import subprocess
import tarfile

from public_surface_checks import compare_llms, request_blocks
from source_json import loads


class RenderedRequestParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = False
        self.elements = []
        self.visible_text = []
        self.heading = None
        self.heading_text = []
        self.section = None
        self.pre_depth = 0
        self.code_depth = 0
        self.code_text = []
        self.paragraph = None
        self.paragraph_depth = 0
        self.paragraph_text = []
        self.pending = []
        self.records = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = attributes.get('style') or ''
        excluded = (tag in ('script', 'style', 'template', 'noscript', 'svg') or
                    'hidden' in attributes or bool(re.search(
                        r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important\s*)?(?:;|$)',
                        style, re.I)))
        hidden = self.ignored or excluded
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.elements.append((tag, hidden))
            self.ignored = hidden
        if hidden:
            return
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.heading = tag
            self.heading_text = []
        if tag == 'pre':
            self.pre_depth += 1
        if tag == 'code' and self.pre_depth and self.section == 'request':
            self.code_depth += 1
            if self.code_depth == 1:
                self.code_text = []
        if self.paragraph and tag == self.paragraph:
            self.paragraph_depth += 1
        elif (tag == 'p' or dict(attrs).get('data-as') == 'p') and self.section == 'pricing' and self.pending:
            self.paragraph = tag
            self.paragraph_depth = 1
            self.paragraph_text = []

    def handle_data(self, data):
        if self.ignored:
            return
        self.visible_text.append(data)
        if self.heading:
            self.heading_text.append(data)
        if self.code_depth:
            self.code_text.append(data)
        if self.paragraph:
            self.paragraph_text.append(data)

    def handle_endtag(self, tag):
        was_hidden = self.ignored
        for index in range(len(self.elements) - 1, -1, -1):
            if self.elements[index][0] == tag:
                del self.elements[index:]
                break
        self.ignored = bool(self.elements and self.elements[-1][1])
        if was_hidden:
            return
        if tag == self.heading:
            heading = ''.join(self.heading_text).replace('\u200b', '').strip()
            self.section = 'request' if heading in ('Request contract', '请求规范') else 'pricing' if heading in ('Cost and request rules', '费用与请求规则') else None
            if self.section == 'request':
                self.pending = []
            self.heading = None
        if tag == 'code' and self.code_depth:
            self.code_depth -= 1
            if self.code_depth == 0:
                value = loads(''.join(self.code_text))
                if not isinstance(value, dict) or not all(k in value for k in ('operationId', 'method', 'path', 'parameters')):
                    raise ValueError('Malformed visible request declaration')
                identity = (value['operationId'], value['method'], value['path'])
                record = {'request': value, 'price_summary': None}
                self.records.setdefault(identity, []).append(record)
                self.pending.append(record)
        if tag == 'pre' and self.pre_depth:
            self.pre_depth -= 1
        if self.paragraph and tag == self.paragraph:
            self.paragraph_depth -= 1
        if self.paragraph and self.paragraph_depth == 0:
            summary = re.sub(r'\s+', ' ', html.unescape(''.join(self.paragraph_text))).strip()
            for record in self.pending:
                record['price_summary'] = summary
            self.pending = []
            self.paragraph = None



def visible_contract(raw):
    parser = RenderedRequestParser()
    parser.feed(raw.decode("utf-8"))
    parser.close()
    return "".join(parser.visible_text), parser.records


def fixed_pages(root, ref):
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    if pointer.get('status') != 'passed':
        raise ValueError('Expected publication is not formal')
    raw = subprocess.check_output(['git', 'archive', ref, 'api-reference', 'zh/api-reference'], cwd=root)
    pages = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith('.mdx'):
                continue
            content = archive.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != pointer.get('files_sha256', {}).get(member.name):
                raise ValueError('Expected rendered page is not bound: ' + member.name)
            records = request_blocks(content.decode('utf-8'))
            if records:
                pages[member.name] = records
    if not pages or not all(any(name.startswith('zh/') == zh for name in pages) for zh in (False, True)):
        raise ValueError('Formal publication has no bilingual request pages')
    return pages


def select_pages(pages, *, full=False):
    if full:
        return sorted(pages)
    selected = set()
    for zh in (False, True):
        names = sorted(name for name in pages if name.startswith('zh/') == zh)
        if names:
            # Both boundaries and evenly spaced interior pages catch truncated
            # deployment inventories; random sampling could miss a stale tail.
            selected.update(names[i * (len(names) - 1) // 15] for i in range(16))
    for name, declarations in pages.items():
        if any(row['request'].get('x-aisa-status') == 'disabled'
               for records in declarations.values() for row in records):
            selected.add(name)
    return sorted(selected)


def check_rendered_pages(pages, *, read_bytes, full=False):
    selected = select_pages(pages, full=full)
    missing, mismatches, observations = [], [], {}

    def inspect(name):
        url = 'https://aisa.one/docs/' + name.removesuffix('.mdx')
        raw = read_bytes('docs-page-' + hashlib.sha256(name.encode()).hexdigest(), url)
        visible, actual = visible_contract(raw)
        errors = compare_llms(pages[name], actual)
        if any(row['request'].get('x-aisa-status') == 'disabled'
               for records in pages[name].values() for row in records):
            notice = '此接口已停用，无法调用' if name.startswith('zh/') else 'This endpoint is disabled and cannot be called'
            if notice not in visible:
                errors.append('disabled_notice_missing')
        return {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                'request_declarations': len(actual), 'mismatches': errors}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(inspect, name): name for name in selected}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                row = future.result()
                observations[name] = row
                mismatches.extend('docs-page:' + name + ':' + error for error in row['mismatches'])
            except Exception as exc:
                missing.append('docs-page:' + name + ':unavailable:' + type(exc).__name__)
    coverage = {locale: {'inventory': sum(name.startswith('zh/') == zh for name in pages),
                         'selected': sum(name.startswith('zh/') == zh for name in selected),
                         'observed': sum(name.startswith('zh/') == zh for name in observations)}
                for locale, zh in (('en', False), ('zh', True))}
    return {'status': 'not_assessed' if missing else ('failed' if mismatches else 'passed'),
            'scope': 'all_formal_pages' if full else 'bilingual_sample_and_all_disabled_pages',
            'full_inventory_checked': full and not missing,
            'coverage': coverage, 'missing_inputs': sorted(missing),
            'mismatches': sorted(mismatches), 'observations': observations}
