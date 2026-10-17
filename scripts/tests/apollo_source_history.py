import copy
import json

from compose_openapi import digest


def undo_object_body_amendment(test, root, doc, source):
    review = json.loads((root / 'docs/current-source-review-20261017/apollo-object-bodies-review.json').read_text())
    test.assertEqual(source['content_hash'], digest(doc))
    test.assertEqual(source['prior_source'], review['prior_source'])
    test.assertEqual(source['content_hash'], review['source_hash'])
    for edit in review['edits']:
        parent = doc
        for key in edit['pointer'][:-1]:
            parent = parent[key]
        test.assertEqual(digest(parent[edit['pointer'][-1]]), edit['after_sha256'])
        parent[edit['pointer'][-1]] = copy.deepcopy(edit['before'])
    source = source['prior_source']
    test.assertEqual(source['content_hash'], digest(doc))
    return source
