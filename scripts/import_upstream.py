#!/usr/bin/env python3
"""Import a configured provider OpenAPI source for review; never publishes it."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
import yaml
from compose_openapi import digest
from runtime_registry import KEY
from import_brave_reference import INDEX_URL as BRAVE_INDEX_URL, import_reference
from import_fred_reference import INDEX as FRED_INDEX_URL, import_reference as import_fred_reference
from import_querit_reference import REFERENCE_URL as QUERIT_REFERENCE_URL, import_reference as import_querit_reference
from import_parallel_legacy_events import SOURCE_URL as PARALLEL_LEGACY_URL, extract as extract_parallel_legacy
from wrapper_twitter_reference import REFERENCE_URL as TWITTER_REFERENCE_URL, import_reference as import_twitter_reference
from wrapper_cloudsway_reference import REFERENCE_URL as CLOUDSWAY_REFERENCE_URL, import_reference as import_cloudsway_reference
from wrapper_cloudsway_full_reference import REFERENCE_URL as CLOUDSWAY_FULL_URL, import_reference as import_cloudsway_full_reference
from source_governance import initial_policy


class OfficialSourceLoader(yaml.SafeLoader):
    """Keep the literal equality operator used in official provider enums."""


# YAML 1.1 tags a plain '=' specially; OpenAPI treats it as an ordinary string.
OfficialSourceLoader.add_constructor(
    'tag:yaml.org,2002:value', OfficialSourceLoader.construct_yaml_str
)


def import_source(provider, url):
    if not KEY.fullmatch(provider) or not url.startswith('https://'):
        raise ValueError('provider id and HTTPS source URL are required')
    if url == FRED_INDEX_URL:
        result = import_fred_reference(provider, url)
        result['info']['x-aisa-source'] = initial_policy(result['info']['x-aisa-source'])
        return result
    def fetch(source_url):
        with urlopen(Request(source_url, headers={"User-Agent": "Mozilla/5.0 AIsa-contract-source-importer"}), timeout=30) as response:
            return response.read()
    metadata = {}
    if url == PARALLEL_LEGACY_URL:
        document = extract_parallel_legacy(fetch(url))
        metadata = document['info'].pop('x-aisa-source')
        metadata.pop('content_hash', None)
    elif url == TWITTER_REFERENCE_URL:
        document, metadata = import_twitter_reference(fetch)
    elif url == CLOUDSWAY_FULL_URL:
        document, metadata = import_cloudsway_full_reference(fetch)
    elif url == CLOUDSWAY_REFERENCE_URL:
        document, metadata = import_cloudsway_reference(fetch)
        metadata['kind'] = 'manual'  # Reviewed public mapping of an official upstream source.
    elif url == BRAVE_INDEX_URL:
        document, metadata = import_reference(fetch)
    elif url == QUERIT_REFERENCE_URL:
        document, metadata = import_querit_reference(fetch)
    else:
        document = yaml.load(fetch(url), Loader=OfficialSourceLoader)
    if not isinstance(document, dict) or not str(document.get('openapi', '')).startswith('3.') or not isinstance(document.get('paths'), dict):
        raise ValueError('source is not an OpenAPI 3 document')
    source_hash = digest(document)
    document.setdefault('info', {})['x-aisa-source'] = {
        'kind': 'provider_openapi', 'url': url,
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'content_hash': source_hash, 'converter': 'scripts/import_upstream.py@2', **metadata,
    }
    document['info']['x-aisa-source'] = initial_policy(document['info']['x-aisa-source'])
    return document


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--provider', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    document = import_source(args.provider, args.url)
    if args.write:
        destination = args.root / 'openapi/upstream' / (args.provider + '.json')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'provider': args.provider, 'operations': sum(len([m for m in item if m in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}]) for item in document['paths'].values()), 'source': document['info']['x-aisa-source'], 'written': args.write}))
