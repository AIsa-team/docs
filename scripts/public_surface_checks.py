"""Read-only public JSON, llms and MCP checks against one fixed Docs publication.

No provider execution. Full JSON equality includes business properties named
'description' or 'example'; no recursive key-name filtering is used.
"""
import hashlib
import html
import io
import json
import re
import subprocess
import tarfile

from source_json import loads

JSON_SURFACES = {
    'website-json': 'https://aisa.one/openapi.json',
    'docs-json': 'https://aisa.one/docs/openapi/openapi.json',
    'docs-root-json': 'https://aisa.one/docs/openapi.json',
}
TEXT_SURFACES = {
    'website-llms': 'https://aisa.one/llms.txt',
    'docs-llms': 'https://aisa.one/docs/llms.txt',
    'docs-llms-full': 'https://aisa.one/docs/llms-full.txt',
    'mcp-llms': 'https://mcp.aisa.one/llms.txt',
}


def same_json(left, right):
    """JSON equality without Python's True == 1 coercion; integers stay exact."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_json(value, right[key]) for key, value in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


def request_blocks(text):
    """Recover rendered declarations, including arbitrary-length safe fences."""
    result = {}
    sections = re.split(r'^#{1,6} (?:Request contract|请求规范)\s*$', text, flags=re.M)[1:]
    for section in sections:
        match = re.search(r'^(`{3,})json(?:[ \t]+[^\n]*)?\s*\n(.*?)\n\1\s*$', section, re.M | re.S)
        if not match:
            continue
        value = loads(match.group(2))
        if not isinstance(value, dict) or not all(key in value for key in ('operationId', 'method', 'path', 'parameters')):
            raise ValueError('Malformed readable request declaration')
        identity = (value['operationId'], value['method'], value['path'])
        # Pricing summary is the paragraph immediately below the managed heading.
        price = re.search(r'^#{1,6} (?:Cost and request rules|费用与请求规则)\s*\n\s*([^\n]+)', section, re.M)
        record = {'request': value, 'price_summary': re.sub(r'\s+', ' ', re.sub(r'\\([\\`*_{}\[\]()#+.!$>-])', r'\1', html.unescape(price.group(1)))).strip() if price else None}
        result.setdefault(identity, []).append(record)
    return result


def fixed_request_blocks(root, ref):
    """Only exact hash-bound English pages; locale JSON is checked separately."""
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    if pointer.get('status') != 'passed':
        raise ValueError('Expected publication is not formal')
    raw = subprocess.check_output(['git', 'archive', ref, 'api-reference'], cwd=root)
    expected = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith('.mdx'):
                continue
            content = archive.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != pointer.get('files_sha256', {}).get(member.name):
                raise ValueError('Expected request page is not bound: ' + member.name)
            for identity, records in request_blocks(content.decode()).items():
                expected.setdefault(identity, []).extend(records)
    if not expected:
        raise ValueError('Formal publication has no readable request declarations')
    return expected


def compare_llms(expected, actual):
    """Require coverage and reject contradictory records for known operations.

    A correctly rendered copy cannot conceal a stale duplicate elsewhere in the
    same text. Multiple identities for an operation are allowed only when every
    identity is explicitly present in the selected publication (e.g. aliases).
    """
    errors = []
    known_ids = {identity[0] for identity in expected}
    for identity in actual:
        if identity[0] in known_ids and identity not in expected:
            errors.append(':'.join(identity) + ':unexpected_operation_identity')
    for identity, records in expected.items():
        candidates = actual.get(identity, [])
        label = ':'.join(identity)
        if not candidates:
            errors.append(label + ':request_missing')
            continue
        # Check both directions: all expected declarations must appear, and
        # every observed declaration for this identity must be authoritative.
        for source, target in ((records, candidates), (candidates, records)):
            for record in source:
                matches = [row for row in target if same_json(row['request'], record['request'])]
                if not matches:
                    errors.append(label + ':request_declaration_mismatch')
                elif not any(row['price_summary'] == record['price_summary'] for row in matches):
                    errors.append(label + ':price_summary_mismatch')
    return sorted(set(errors))


def check_surfaces(spec, expected_hash, accepted_refs, *, read_bytes, expected_requests):
    """Return every independent failure; an unavailable surface cannot pass."""
    mismatches, missing, observations = [], [], {}
    for name, url in JSON_SURFACES.items():
        try:
            raw = read_bytes(name, url)
            value = loads(raw)
            observations[name] = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest()}
            if not same_json(value, spec):
                mismatches.append(name + ':complete_openapi_mismatch')
        except Exception as exc:
            missing.append(name + ':unavailable:' + type(exc).__name__)
    mcp = None
    try:
        url = 'https://mcp.aisa.one/contract-version'
        mcp = loads(read_bytes('mcp-version', url))
        observations['mcp-version'] = mcp
        refs = mcp.get('docsRefs')
        if not isinstance(refs, list) or len(refs) != 1 or refs[0] not in accepted_refs:
            mismatches.append('mcp:docs_revision_mismatch')
        hashes = mcp.get('documentHashes')
        if mcp.get('state') != 'loaded' or not isinstance(hashes, dict) or not hashes:
            mismatches.append('mcp:loaded_provenance_unverified')
        else:
            providers = spec.get('info', {}).get('x-aisa-document', {}).get('providers', {})
            for provider, digest in hashes.items():
                if providers.get(provider, {}).get('document_hash') != digest:
                    mismatches.append('mcp:' + provider + ':document_hash_mismatch')
    except Exception as exc:
        missing.append('mcp-version:unavailable:' + type(exc).__name__)
    for name, url in TEXT_SURFACES.items():
        try:
            raw = read_bytes(name, url)
            text = raw.decode('utf-8')
            observations[name] = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest()}
            if name == 'website-llms':
                if expected_hash not in text or not any(ref in text for ref in accepted_refs):
                    mismatches.append(name + ':formal_version_missing')
                if 'https://aisa.one/openapi.json' not in text or not any('/' + ref + '/openapi.yaml' in text for ref in accepted_refs):
                    mismatches.append(name + ':versioned_schema_links_missing')
            elif name == 'docs-llms':
                if expected_hash not in text:
                    mismatches.append(name + ':formal_version_missing')
                if 'openapi' not in text.lower() or '.json' not in text.lower():
                    mismatches.append(name + ':json_discovery_missing')
            elif name == 'mcp-llms':
                if not mcp or not all(ref in text for ref in mcp.get('docsRefs', [])) or not mcp.get('docsRefs'):
                    mismatches.append(name + ':loaded_revision_missing')
            elif expected_requests:
                actual = request_blocks(text)
                mismatches.extend(name + ':' + error for error in compare_llms(expected_requests, actual))
                observations[name]['request_operations_compared'] = len(expected_requests)
        except Exception as exc:
            missing.append(name + ':unavailable:' + type(exc).__name__)
    if not expected_requests:
        missing.append('docs-llms-full:fixed_readable_request_declarations_missing')
    return {'scope': 'complete JSON; hash-bound English llms requests and price summaries; MCP loaded source and index',
            'observations': observations, 'missing_inputs': sorted(set(missing)), 'mismatches': sorted(set(mismatches))}
