"""Read exact embedded OpenAPI declarations from official TwitterAPI pages."""
import hashlib
import re
from urllib.parse import urlsplit

import yaml

VERSION = 'scripts/import_twitter_endpoint.py@1'
ENDPOINTS = frozenset({
    'create_tweet_v2', 'delete_tweet_v2', 'like_tweet_v2', 'unlike_tweet_v2',
    'retweet_tweet_v2', 'follow_user_v2', 'unfollow_user_v2',
    'upload_media_v2', 'user_login_v2',
})
PREFIX = 'https://docs.twitterapi.io/api-reference/endpoint/'


def accepts(url):
    return url in {PREFIX + name + '.md' for name in ENDPOINTS}


def extract(raw, url, loader):
    """Fail closed on page/route drift; never turn prose or examples into schemas."""
    if not accepts(url):
        raise ValueError('unreviewed Twitter endpoint source URL')
    text = raw.decode('utf-8')
    blocks = re.findall(r'^(`{3,})yaml ([A-Z]+) (\S+)\n(.*?)^\1\s*$', text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError('expected one declared OpenAPI YAML block')
    _, method, path, payload = blocks[0]
    expected = '/twitter/' + urlsplit(url).path.rsplit('/', 1)[-1][:-3]
    document = yaml.load(payload, Loader=loader)
    if (path != expected or method != 'POST' or not isinstance(document, dict)
            or not str(document.get('openapi', '')).startswith('3.')
            or set(document.get('paths', {})) != {expected}
            or set(document['paths'][expected]) != {'post'}
            or document.get('servers') != [{'url': 'https://api.twitterapi.io'}]):
        raise ValueError('official Twitter endpoint binding changed')
    return document, {'converter': VERSION, 'official_reference_sha256': hashlib.sha256(raw).hexdigest()}
