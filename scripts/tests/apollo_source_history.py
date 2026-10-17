import copy
import json

from compose_openapi import digest


def undo_contact_bulk_body_amendment(test, root, doc, source):
    review = json.loads((root / 'docs/current-source-review-20261017/apollo-contact-bulk-body-review.json').read_text())
    test.assertEqual(source['content_hash'], digest(doc))
    test.assertEqual(source['prior_source'], review['prior_source'])
    test.assertEqual(source['content_hash'], review['source_hash'])
    operation = doc['paths'][review['source_path']]['post']
    test.assertEqual(digest(operation), review['amended_operation_sha256'])
    doc['paths'][review['source_path']]['post'] = copy.deepcopy(review['prior_operation'])
    source = source['prior_source']
    test.assertEqual(source['content_hash'], digest(doc))
    return source


def undo_query_array_amendment(test, root, doc, source):
    source = undo_contact_bulk_body_amendment(test, root, doc, source)
    review = json.loads((root / 'docs/current-source-review-20261017/apollo-query-arrays-review.json').read_text())
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


def undo_object_body_amendment(test, root, doc, source):
    source = undo_query_array_amendment(test, root, doc, source)
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
