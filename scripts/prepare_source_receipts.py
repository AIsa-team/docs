#!/usr/bin/env python3
"""Combine committed review evidence with newer workflow observations, without review."""
import argparse
import copy
import json
from pathlib import Path

from source_governance import receipt_key, timestamp


def merge_evidence(*packets):
    result = {'schema_version': 1, 'receipts': {}, 'attempts': {}}
    for packet in packets:
        if not isinstance(packet, dict) or packet.get('schema_version') != 1:
            raise ValueError('Unsupported source evidence packet')
        for section, field in (('receipts', 'last_successful_review_at'), ('attempts', 'checked_at')):
            rows = packet.get(section, {})
            if not isinstance(rows, dict):
                raise ValueError('Invalid source evidence section: ' + section)
            for key, row in rows.items():
                if not isinstance(row, dict) or not isinstance(key, str) or timestamp(row.get(field)) is None:
                    raise ValueError('Invalid source evidence observation: ' + section)
                if section == 'receipts' and receipt_key({'content_hash': row.get('source_hash'),
                                                          'policy_revision': row.get('policy_revision')}) != key:
                    raise ValueError('Receipt key does not match its source/policy binding')
                previous = result[section].get(key)
                if previous is not None:
                    at, prior = timestamp(row[field]), timestamp(previous[field])
                    if at == prior and row != previous:
                        raise ValueError('Conflicting source evidence at the same observation time')
                    if at <= prior:
                        continue
                result[section][key] = copy.deepcopy(row)
    return result


def prepare(reviewed, cache):
    # The reviewed input is mandatory; an absent cache is normal on a new runner.
    packets = [json.loads(reviewed.read_text())]
    if cache.exists():
        packets.append(json.loads(cache.read_text()))
    merged = merge_evidence(*packets)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(cache.suffix + '.tmp')
    temporary.write_text(json.dumps(merged, indent=2, sort_keys=True) + '\n')
    temporary.replace(cache)
    return merged


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    merged = prepare(args.reviewed, args.cache)
    print(json.dumps({'receipts': len(merged['receipts']), 'attempts': len(merged['attempts']),
                      'scope': 'existing evidence only; timestamps and release gates unchanged'}))
