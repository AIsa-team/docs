"""Customer-facing wording for reviewed upstream prose (Spec #1285 R1).

Reviewed upstream response sources keep their original declarations byte for
byte (their review binds them). Some of that prose names the upstream
supplier, which customer-visible Docs must never do. The composer rewrites
only these exact, reviewed phrases in published prose; examples, enums,
defaults and provenance metadata are data and are never touched.
"""
from __future__ import annotations

# (internal source phrase, customer phrase). Longest phrases first.
REWRITES = (
    ('not SocialFetch-hosted assets', 'not AIsa-hosted assets'),
    ('a SocialFetch-hosted asset', 'an AIsa-hosted asset'),
    ('SocialFetch-hosted', 'AIsa-hosted'),
    ('Whether SocialFetch stored', 'Whether AIsa stored'),
    ('SocialFetch storage', 'AIsa hosted-media storage'),
)
PROSE_KEYS = frozenset({'description', 'summary', 'title'})
DATA_KEYS = frozenset({'example', 'examples', 'default', 'enum', 'const', 'x-aisa-source',
                       'x-aisa-response-source', 'x-aisa-source-provenance'})


def rewrite_text(text):
    for source, customer in REWRITES:
        text = text.replace(source, customer)
    return text


def apply(document):
    """Return the document with reviewed supplier phrases reworded in prose."""
    def walk(node, key=None):
        if isinstance(node, dict):
            return {name: (value if name in DATA_KEYS else walk(value, name)) for name, value in node.items()}
        if isinstance(node, list):
            return [walk(value, key) for value in node]
        if isinstance(node, str) and key in PROSE_KEYS:
            return rewrite_text(node)
        return node
    return walk(document)
