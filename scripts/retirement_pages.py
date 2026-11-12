"""Archived pages of editorially retired routes (docs/human-api-retirements*.json)."""
import json
from pathlib import Path


def retirement_rows(root):
    """Return {(METHOD, full path): page} from every presentation-only policy."""
    rows = {}
    for policy in sorted((Path(root) / 'docs').glob('human-api-retirements*.json')):
        config = json.loads(policy.read_text())
        if config.get('scope') != 'human_presentation_only' or config.get('formal_publication') is not False:
            raise ValueError('Retirement policy must remain presentation-only')
        for row in config['operations']:
            key = (row['method'].upper(), row['path'])
            if key in rows:
                raise ValueError('Route is retired by more than one policy')
            rows[key] = row['page']
    return rows
