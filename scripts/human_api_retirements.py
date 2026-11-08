"""Editorial retirement of human pages; never modifies runtime facts or contracts."""
import json
import re
from pathlib import Path


def archive(row, zh, guide):
    title = ('已退役：' if zh else 'Retired: ') + row['title']
    text = ('此旧接口已退役，请勿再调用或复用旧 OAuth 凭据。请通过现有 AIsa Social Connect 重新授权 X 账户。'
            if zh else 'This legacy endpoint is retired. Do not call it or reuse its old OAuth credentials. Reauthorize the X account through existing AIsa Social Connect.')
    label = '迁移步骤与能力限制' if zh else 'Migration steps and capability limits'
    prefix = 'zh/' if zh else ''
    return ('---\ntitle: '+json.dumps(title,ensure_ascii=False)+'\nnoindex: true\n'
            'x-aisa-human-retirement: true\n---\n\n<Warning>'+text+'</Warning>\n\n'
            '`'+row['method']+' '+row['path']+'`\n\n'
            '['+label+'](/'+prefix+guide+')\n')


def apply_retirements(root, changes):
    root = Path(root)
    source = root / 'docs/human-api-retirements.json'
    if not source.exists():
        return
    config = json.loads(source.read_text())
    if config.get('scope') != 'human_presentation_only' or config.get('formal_publication') is not False:
        raise ValueError('Retirement policy must remain presentation-only')
    rows = config['operations']
    by_route = {(row['method'], row['path']): row for row in rows}
    candidates = set(changes)
    for prefix in ('api-reference', 'zh/api-reference'):
        candidates.update((root / prefix).rglob('*.mdx'))
    hidden = set()
    # Include stable archived URLs even after the OpenAPI frontmatter is removed.
    destinations = {root / (prefix+row['page']+'.mdx'): row
                    for row in rows for prefix in ('', 'zh/')}
    for path in candidates:
        if path.suffix != '.mdx':
            continue
        text = changes.get(path, path.read_text() if path.exists() else '')
        match = re.search(r'^openapi:\s*[\"\']?\S+\.json\s+([A-Z]+)\s+([^\s\"\']+)', text, re.M)
        if match and (match[1], match[2]) in by_route:
            destinations[path] = by_route[match[1], match[2]]
    for path, row in destinations.items():
        rel = path.relative_to(root).as_posix()
        changes[path] = archive(row, rel.startswith('zh/'), config['guide'])
        hidden.add(rel.removesuffix('.mdx'))
    nav = root / 'docs.json'
    if nav.exists():
        document = json.loads(changes.get(nav, nav.read_text()))
        def prune(node):
            if isinstance(node,list):
                values = [prune(v) for v in node if not isinstance(v,str) or v not in hidden]
                return [v for v in values if not (isinstance(v,dict) and 'group' in v and v.get('pages') == [])]
            if isinstance(node,dict):
                return {k:prune(v) for k,v in node.items()}
            return node
        document['navigation'] = prune(document.get('navigation', {}))
        changes[nav] = json.dumps(document,indent=2,ensure_ascii=False)+'\n'
