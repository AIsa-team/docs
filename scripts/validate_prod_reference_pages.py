"""Validate production reference page definitions independently of formal exports."""
import argparse
import json
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_reference_pages(root):
    """Validate every moved schema reference and both language identities."""
    documents = {}
    checked = 0
    for prefix in ('api-reference', 'zh/api-reference'):
        for page in (root / prefix).rglob('*.mdx'):
            text = page.read_text()
            match = re.search(r'^openapi:\s*[\"\']?(reference-contracts/[^\s\"\']+\.json)\s+(\w+)\s+([^\s\"\']+)', text, re.M)
            frontmatter = re.search(r'^openapi:\s*(.+)$', text, re.M)
            if not frontmatter or not frontmatter[1].lstrip("\"'").startswith('reference-contracts/'):
                continue
            require(match is not None, 'Malformed production reference: ' + page.relative_to(root).as_posix())
            name, method, path = match.groups()
            require(re.fullmatch(r'reference-contracts/(?:zh/)?[A-Za-z0-9_.-]+\.json',name), 'Unsafe reference schema path')
            require(name.startswith('reference-contracts/zh/') == prefix.startswith('zh/'), 'Reference schema language differs')
            if name not in documents:
                require(not (root / name).is_symlink(), 'Reference schema symlink is forbidden')
                documents[name] = json.loads((root / name).read_text())
            operation = documents[name].get('paths',{}).get(path,{}).get(method.lower())
            require(isinstance(operation,dict), 'Reference page operation is missing: ' + page.relative_to(root).as_posix())
            identity = re.search(r'^x-aisa-operation-id:\s*(.+)$',text,re.M)
            if identity:
                expected = json.loads(identity[1])
                candidates = {operation.get('operationId')}
                candidates.update(a.get('operation_id') for a in operation.get('x-aisa-identity',{}).get('historical_aliases',[]))
                require(expected in candidates, 'Reference page identity differs: ' + page.relative_to(root).as_posix())
            checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        count = validate_reference_pages(args.root)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print('Validated production reference pages: ' + str(count))


if __name__ == '__main__':
    main()
