"""Read-only public JSON, llms and MCP checks against one fixed Docs publication.

No provider execution. Full JSON equality includes business properties named
'description' or 'example'; no recursive key-name filtering is used.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
import re
import subprocess
import tarfile
from urllib.parse import urlsplit

from source_json import loads
import yaml

SALES_CATALOG = 'https://aisa.one/api/sales-api-data'
MCP_SERVERS = 'https://mcp.aisa.one/servers'
MCP_PAGE = 'https://aisa.one/mcp'
DISCOVERY_PAGE = 'https://aisa.one/docs/guides/agent-discovery.md'
PROVIDER_PAGE = 'https://aisa.one/api/{}'
# An impossible slug: the website must not serve a 200 page for it.
UNKNOWN_PROVIDER_SLUG = 'no-such-provider-page-9f3c7e1a'
# Retired website pages that must no longer answer 200.
RETIRED_PROVIDER_SLUGS = ('image-generation-via-chat',)
# The website groups publication operations without a registry provider (the
# OpenAI/Anthropic/Gemini model routes and `account`) under this sales id.
SALES_UNREGISTERED_PROVIDER = 'models'
SOFT_404_TITLE = 'API Not Found'
# A provider page may answer with exactly one temporary same-origin redirect
# (307/308 to https://aisa.one/...) to its curated card; the target must then
# be a 200 page that is not the soft 404. Any other redirect is a failure.
PROVIDER_PAGE_REDIRECTS = (307, 308)
PROVIDER_PAGE_ORIGIN = 'https://aisa.one'
# Agent setup guide (https://aisa.one/llms.txt) lines that contradict the CLI
# page ("Success on /v1/models ... does not prove authenticated business
# access") and the Errors page table (no key: 402 MPP challenge / 404 / 401
# missing_api_key by route; invalid key: 401). Presence is a mismatch.
WEBSITE_LLMS_RULE_CONFLICTS = {
    'http_verification_rule_conflict': 'with the Bearer header returns 200',
    'no_credential_error_rule_conflict': '`401`: not signed in or invalid key',
}
# Agent Discovery page (string presence/absence on the rendered Markdown body,
# after the generated `>` header block). Matched case-insensitively.
DISCOVERY_PAGE_RULES = {
    'agent_setup_guide_link_missing': ('required', ('https://aisa.one/llms.txt', 'agent setup guide')),
    'product_llms_label_present': ('forbidden', ('product llms.txt',)),
    'mcp_primary_flow_missing': ('required', ('https://mcp.aisa.one/mcp', 'oauth')),
    'http_fallback_rule_missing': ('required', ('fallback',)),
    'http_key_primary_flow_present': ('forbidden', ('requests use bearer token authentication with an aisa api key',)),
}
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


def fixed_payment_bytes(root, ref):
    """Select the payment subset from the same hash-bound formal graph."""
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    path = 'discovery/openapi.json'
    raw = subprocess.check_output(['git', 'show', ref + ':' + path], cwd=root)
    if (pointer.get('status') != 'passed' or
            hashlib.sha256(raw).hexdigest() != pointer.get('files_sha256', {}).get(path)):
        raise ValueError('Expected payment discovery is not formally bound')
    value = loads(raw)
    if not isinstance(value, dict) or not value.get('paths'):
        raise ValueError('Expected payment discovery has no operations')
    return raw


def fixed_mcp_sources(root, ref, spec):
    """Required managed sources and permitted residual inputs from formal Git.

    Module names are not provider names: a composed module can load several
    native files. Bind the complete union of raw files, rather than accepting a
    consumer's self-selected subset of document hashes.
    """
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    if pointer.get('status') != 'passed':
        raise ValueError('Expected publication is not formal')
    hashes = pointer.get('files_sha256', {})
    def bound(path):
        raw = subprocess.check_output(['git', 'show', ref + ':' + path], cwd=root)
        if hashlib.sha256(raw).hexdigest() != hashes.get(path):
            raise ValueError('MCP source is not formally bound: ' + path)
        return raw
    providers = spec.get('info', {}).get('x-aisa-document', {}).get('providers', {})
    required = {provider + '.json' for provider, metadata in providers.items()
                if metadata.get('document_hash')}
    if not required:
        raise ValueError('No managed MCP sources')
    registry = yaml.safe_load(bound('openapi/registry.yaml'))
    residual = {name.removesuffix('.json') + '.json'
                for entry in registry['providers'].values()
                for name in (entry or {}).get('legacy_sources', [])}
    allowed = {}
    for filename in sorted(required | residual):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.json', filename):
            raise ValueError('Invalid MCP source filename')
        path = 'openapi/' + filename
        if path not in hashes and filename not in required:
            continue  # A declared legacy source may have been superseded.
        allowed[filename] = 'sha256:' + hashlib.sha256(bound(path)).hexdigest()
    return {'required': sorted(required), 'allowed': allowed}


def compare_mcp_sources(expected, actual):
    errors, union = [], {}
    sources = actual.get('sourceHashes')
    if not expected or not isinstance(sources, dict) or not sources:
        return ['mcp:source_hashes_unverified']
    for module, rows in sources.items():
        if not isinstance(module, str) or not isinstance(rows, dict) or not rows:
            errors.append('mcp:source_hashes_invalid')
            continue
        for filename, digest in rows.items():
            if filename not in expected['allowed']:
                errors.append('mcp:' + str(filename) + ':unexpected_source_file')
            elif expected['allowed'][filename] != digest:
                errors.append('mcp:' + filename + ':source_hash_mismatch')
            if filename in union and union[filename] != digest:
                errors.append('mcp:' + str(filename) + ':conflicting_source_hash')
            union[filename] = digest
    errors.extend('mcp:' + filename + ':source_file_missing'
                  for filename in set(expected['required']) - set(union))
    if actual.get('missingProvenance') or actual.get('conflictingDocuments'):
        errors.append('mcp:loaded_provenance_unverified')
    return sorted(set(errors))


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


def check_surfaces(spec, expected_hash, accepted_refs, *, read_bytes, expected_requests,
                   expected_payment=None, expected_mcp_sources=None):
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
    # API root remains the reviewed payment subset, never the full ordinary API.
    if expected_payment is None:
        missing.append('mpp-json:fixed_formal_discovery_missing')
    else:
        try:
            url = 'https://api.aisa.one/openapi.json'
            raw = read_bytes('mpp-json', url)
            actual = loads(raw)
            observations['mpp-json'] = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                'expected_sha256': hashlib.sha256(expected_payment).hexdigest()}
            if raw != expected_payment:
                mismatches.append('mpp-json:formal_bytes_mismatch')
            if not same_json(actual, loads(expected_payment)):
                mismatches.append('mpp-json:payment_contract_mismatch')
        except Exception as exc:
            missing.append('mpp-json:unavailable:' + type(exc).__name__)
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
        mismatches.extend(compare_mcp_sources(expected_mcp_sources, mcp))
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
                mismatches.extend(name + ':' + code for code, needle in WEBSITE_LLMS_RULE_CONFLICTS.items() if needle in text)
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
    return {'scope': 'complete JSON; exact formal MPP subset; hash-bound English llms requests and price summaries; MCP loaded source and index',
            'observations': observations, 'missing_inputs': sorted(set(missing)), 'mismatches': sorted(set(mismatches))}


def fixed_sales_catalog(root, ref):
    """Expected sales identity and per-provider operation counts from formal Git.

    The website's `endpoint_count` is the number of non-disabled operations the
    hash-bound sales view attributes to a registry provider. Operations without
    a registry provider are the website's `models` group.
    """
    pointer = loads(subprocess.check_output(['git', 'show', ref + ':docs/publication/current.json'], cwd=root))
    if pointer.get('status') != 'passed':
        raise ValueError('Expected publication is not formal')
    binding = pointer.get('sales_catalog') or {}
    path = binding.get('path')
    if path != 'docs/publication/sales-catalog.json':
        raise ValueError('Expected publication has no bound sales view')
    raw = subprocess.check_output(['git', 'show', ref + ':' + path], cwd=root)
    if hashlib.sha256(raw).hexdigest() != binding.get('sha256') or pointer.get('files_sha256', {}).get(path) != binding.get('sha256'):
        raise ValueError('Expected sales view is not formally bound')
    document = loads(raw).get('document', {})
    counts = {}
    for item in document.get('paths', {}).values():
        for method, operation in item.items():
            if method not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options') or not isinstance(operation, dict):
                continue
            if operation.get('x-aisa-status') == 'disabled':
                continue
            provider = operation.get('x-aisa-registry-provider') or SALES_UNREGISTERED_PROVIDER
            counts[provider] = counts.get(provider, 0) + 1
    if not counts:
        raise ValueError('Expected sales view has no operations')
    release = pointer.get('contract_release')
    if not isinstance(release, str) or not re.fullmatch(r'[0-9a-f]{64}', release):
        raise ValueError('Expected publication has no contract release')
    return {'docs_ref': ref, 'contract_release': release, 'provider_counts': counts,
            'sha256': hashlib.sha256(raw).hexdigest()}


def html_title(raw):
    match = re.search(rb'<title[^>]*>(.*?)</title>', raw, re.S | re.I)
    return html.unescape(match.group(1).decode('utf-8', 'replace')).strip() if match else ''


def page_text(raw):
    """Visible text of an HTML page: no scripts/styles/tags, single spaces."""
    text = raw.decode('utf-8', 'replace')
    text = re.sub(r'<(script|style)\b.*?</\1\s*>', ' ', text, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def mcp_page_numbers(text):
    """Headline counts quoted on the MCP page; per-category rows are smaller."""
    def numbers(pattern):
        return [int(value.replace(',', '')) for value in re.findall(pattern, text)]
    return {'tools': numbers(r'(\d[\d,]*) (?:AIsa data )?tools\b') + numbers(r'(\d[\d,]*) reachable\b'),
            'servers': numbers(r'(\d[\d,]*) servers\b'),
            'categories': numbers(r'(\d[\d,]*) categories\b')}


def mcp_page_prices(text):
    """`$<amount> <operation or tool name>` pairs; names need an underscore."""
    return [(amount, name) for amount, name in
            re.findall(r'\$(\d+(?:\.\d+)?)\s+([a-z][a-z0-9]*(?:_[a-z0-9]+)+)', text)]


def quoted_operations(sales):
    """operation_id -> quote amount from the live sales catalog."""
    quotes = {}
    for operation in sales.get('operations', []):
        if isinstance(operation, dict) and isinstance(operation.get('operation_id'), str):
            quotes[operation['operation_id']] = (operation.get('quote') or {}).get('amount')
    return quotes


def match_operation(name, quotes):
    """MCP tool names drop the HTTP method prefix of the operation id."""
    if name in quotes:
        return [name]
    return sorted(identity for identity in quotes if re.sub(r'^(get|post|put|patch|delete)_', '', identity) == name)


def compare_mcp_page(text, servers, sales):
    """MCP page headline figures versus the live `/servers` catalog and sales quotes.

    `toolCount` in `/servers` is the duplicate-inclusive sum of every server's
    own tool count: a tool pinned under several aliased servers is counted once
    per server. It is not the number of distinct tools reachable through
    `search`. The page must print that summed figure as its largest tool
    number; per-category rows are smaller and are not compared.

    Example prices are compared exactly (Decimal equality) for fixed and
    usage_based quotes alike: the page derives its figure from the same sales
    catalog at build time, so a rounded or stale figure is a mismatch.
    """
    errors, observed = [], mcp_page_numbers(text)
    counts = {'tools': servers.get('toolCount'),  # duplicate-inclusive sum over servers
              'servers': servers.get('serverCount'),
              'categories': sum(1 for row in servers.get('entrypoints', []) if isinstance(row, dict) and row.get('kind') == 'category')}
    for key, expected in counts.items():
        values = observed[key]
        if not values:
            continue
        code = {'tools': 'tool', 'servers': 'server', 'categories': 'category'}[key] + '_count'
        if not isinstance(expected, int) or isinstance(expected, bool):
            errors.append('mcp-servers:' + code + '_invalid')
        elif (max(values) != expected) if key == 'tools' else any(value != expected for value in values):
            errors.append('website-mcp-page:' + code + '_mismatch')
    if not observed['tools'] and not observed['servers']:
        errors.append('website-mcp-page:counts_unparsed')
    quotes = quoted_operations(sales)
    for amount, name in mcp_page_prices(text):
        matches = match_operation(name, quotes)
        if not matches:
            errors.append('website-mcp-page:' + name + ':example_operation_unknown')
        elif len(matches) > 1:
            errors.append('website-mcp-page:' + name + ':example_operation_ambiguous')
        else:
            quoted = quotes[matches[0]]
            try:
                same = Decimal(str(quoted)) == Decimal(amount)
            except (InvalidOperation, ValueError, TypeError):
                same = False
            if not same:
                errors.append('website-mcp-page:' + name + ':example_price_mismatch')
    return sorted(set(errors)), {'page_numbers': observed, 'catalog_counts': counts,
                                 'example_prices': len(mcp_page_prices(text))}


def compare_sales_catalog(sales, expected, accepted_refs):
    errors = []
    if sales.get('docs_revision') not in accepted_refs:
        errors.append('website-sales-catalog:docs_revision_mismatch')
    if sales.get('contract_release') != expected['contract_release']:
        errors.append('website-sales-catalog:contract_release_mismatch')
    live = {}
    for provider in sales.get('providers', []):
        if not isinstance(provider, dict) or not isinstance(provider.get('id'), str):
            errors.append('website-sales-catalog:provider_record_invalid')
            continue
        live[provider['id']] = provider.get('endpoint_count')
    for name, count in expected['provider_counts'].items():
        if name not in live:
            errors.append('website-sales-catalog:' + name + ':provider_missing')
        elif live[name] != count or isinstance(live[name], bool):
            errors.append('website-sales-catalog:' + name + ':endpoint_count_mismatch')
    errors.extend('website-sales-catalog:' + name + ':provider_not_in_publication'
                  for name in live if name not in expected['provider_counts'])
    return sorted(set(errors))


def compare_discovery_page(raw):
    """String rules on the page body; the generated `>` header is skipped."""
    lines = raw.decode('utf-8').splitlines()
    body = []
    for line in lines:
        if not body and (not line.strip() or line.startswith('>')):
            continue
        body.append(line)
    text = '\n'.join(body).lower()
    errors = []
    for code, (mode, needles) in DISCOVERY_PAGE_RULES.items():
        present = [needle in text for needle in needles]
        if (mode == 'required' and not all(present)) or (mode == 'forbidden' and any(present)):
            errors.append('docs-discovery-page:' + code)
    return sorted(errors)


def read_provider_page(name, url, read_page):
    """One request plus at most one accepted same-origin temporary redirect.

    `read_page(name, url)` returns `(status, body)` or `(status, body, location)`
    for a single request without following redirects. Returns
    `(outcome, observation)` where outcome is 'ok', 'not_found', 'http',
    'redirect_offsite' or 'redirect_target_not_found'.
    """
    status, raw, *rest = read_page(name, url)
    location = rest[0] if rest else None
    observation = {'status': status, 'title': html_title(raw)}
    if status in PROVIDER_PAGE_REDIRECTS:
        observation['location'] = location
        parts = urlsplit(location) if isinstance(location, str) else None
        if (parts is None or parts.scheme + '://' + (parts.netloc or '') != PROVIDER_PAGE_ORIGIN
                or parts.username or parts.password or not parts.path.startswith('/')):
            return 'redirect_offsite', observation
        target_slug = parts.path.rstrip('/').rsplit('/', 1)[-1] or 'root'
        target_status, target_raw, *_ = read_page(name + ':' + target_slug, location)
        observation['target'] = {'status': target_status, 'title': html_title(target_raw)}
        if target_status != 200 or SOFT_404_TITLE in observation['target']['title']:
            return 'redirect_target_not_found', observation
        return 'ok', observation
    if status != 200:
        return 'http', observation
    if SOFT_404_TITLE in observation['title']:
        return 'not_found', observation
    return 'ok', observation


def check_provider_pages(provider_ids, read_page):
    """Every publication provider has a real website page; unknown/retired slugs do not."""
    mismatches, missing, observations = [], [], {}
    for name in sorted(provider_ids):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*', name):
            mismatches.append('website-provider-pages:' + name + ':invalid_provider_id')
            continue
        try:
            outcome, observation = read_provider_page('website-provider-page:' + name, PROVIDER_PAGE.format(name), read_page)
            observations[name] = observation
            if outcome == 'http':
                mismatches.append('website-provider-pages:' + name + ':http_' + str(observation['status']))
            elif outcome != 'ok':
                mismatches.append('website-provider-pages:' + name + ':' + outcome)
        except Exception as exc:
            missing.append('website-provider-pages:' + name + ':unavailable:' + type(exc).__name__)
    for name, code in [(UNKNOWN_PROVIDER_SLUG, 'unknown-slug:unknown_slug_returns_200'),
                       *((slug, slug + ':retired_page_returns_200') for slug in RETIRED_PROVIDER_SLUGS)]:
        try:
            # A redirect is not followed here: the slug itself must not be a 200 page.
            status, raw, *_ = read_page('website-provider-page:' + name, PROVIDER_PAGE.format(name))
            observations[name] = {'status': status, 'title': html_title(raw)}
            if status == 200 and SOFT_404_TITLE not in observations[name]['title']:
                mismatches.append('website-provider-pages:' + code)
            elif status == 200:
                mismatches.append('website-provider-pages:' + code.split(':')[0] + ':soft_404_returns_200')
        except Exception as exc:
            missing.append('website-provider-pages:' + name + ':unavailable:' + type(exc).__name__)
    return mismatches, missing, observations


def check_website_surfaces(spec, accepted_refs, *, read_bytes, read_page, expected_sales=None):
    """Website provider pages, MCP page, sales catalog and discovery page.

    Independent codes per surface; a surface that cannot be read is a missing
    input, never a pass. No provider execution and no credentials.
    """
    mismatches, missing, observations = [], [], {}
    sales = None
    try:
        raw = read_bytes('website-sales-catalog', SALES_CATALOG)
        sales = loads(raw)
        if not isinstance(sales, dict) or not isinstance(sales.get('providers'), list):
            raise ValueError('Sales catalog has no provider list')
        observations['website-sales-catalog'] = {'url': SALES_CATALOG, 'sha256': hashlib.sha256(raw).hexdigest(),
            'docs_revision': sales.get('docs_revision'), 'contract_release': sales.get('contract_release'),
            'freshness': sales.get('freshness'), 'providers': len(sales['providers'])}
        if expected_sales is None:
            missing.append('website-sales-catalog:fixed_formal_sales_view_missing')
        else:
            mismatches.extend(compare_sales_catalog(sales, expected_sales, accepted_refs))
    except Exception as exc:
        missing.append('website-sales-catalog:unavailable:' + type(exc).__name__)
    providers = spec.get('info', {}).get('x-aisa-document', {}).get('providers', {})
    provider_ids = {name for name, metadata in providers.items() if isinstance(metadata, dict) and metadata.get('document_hash')}
    if sales is not None:
        provider_ids.update(row['id'] for row in sales['providers'] if isinstance(row, dict) and isinstance(row.get('id'), str))
    if not provider_ids:
        missing.append('website-provider-pages:no_publication_providers')
    else:
        pages, unavailable, observed = check_provider_pages(provider_ids, read_page)
        mismatches.extend(pages)
        missing.extend(unavailable)
        observations['website-provider-pages'] = observed
    try:
        servers = loads(read_bytes('mcp-servers', MCP_SERVERS))
        if not isinstance(servers, dict):
            raise ValueError('MCP catalog is not an object')
        try:
            text = page_text(read_bytes('website-mcp-page', MCP_PAGE))
            if sales is None:
                missing.append('website-mcp-page:sales_quotes_unavailable')
            errors, observed = compare_mcp_page(text, servers, sales or {})
            mismatches.extend(errors)
            observations['website-mcp-page'] = observed
        except Exception as exc:
            missing.append('website-mcp-page:unavailable:' + type(exc).__name__)
    except Exception as exc:
        missing.append('mcp-servers:unavailable:' + type(exc).__name__)
    try:
        raw = read_bytes('docs-discovery-page', DISCOVERY_PAGE)
        observations['docs-discovery-page'] = {'url': DISCOVERY_PAGE, 'sha256': hashlib.sha256(raw).hexdigest()}
        mismatches.extend(compare_discovery_page(raw))
    except Exception as exc:
        missing.append('docs-discovery-page:unavailable:' + type(exc).__name__)
    return {'scope': 'website provider pages (200 and not the soft 404, or one same-origin 307/308 to such a page; unknown and retired slugs not 200); MCP page headline counts versus /servers (toolCount is the duplicate-inclusive per-server sum) and exact example prices versus sales quotes; sales catalog revision, release and per-provider counts; Agent Discovery page rules',
            'observations': observations, 'missing_inputs': sorted(set(missing)), 'mismatches': sorted(set(mismatches))}
