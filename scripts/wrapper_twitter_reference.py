"""Read the owning service's pinned Python declarations without importing its code."""
import ast
import hashlib

REVISION = '9481772229feb96eed7fef509234d089cd0d7ec3'
ROOT = 'https://raw.githubusercontent.com/AIsa-team/AisaTwitterAuthService/' + REVISION + '/'
REFERENCE_URL = ROOT + 'app/api/routes/twitter.py'
SCHEMA_URL = ROOT + 'app/schemas/twitter.py'
VERSION = 'scripts/wrapper_twitter_reference.py@1'


def convert_reference(routes_raw, schemas_raw):
    routes, schemas = ast.parse(routes_raw), ast.parse(schemas_raw)
    handlers = [n for n in routes.body if isinstance(n, ast.FunctionDef) and n.name == 'delete_twitter']
    if len(handlers) != 1:
        raise ValueError('delete_twitter handler must exist exactly once')
    handler = handlers[0]
    decorators = [n for n in handler.decorator_list if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and ast.unparse(n.func) == 'router.post' and n.args and ast.literal_eval(n.args[0]) == '/delete_twitter']
    payload = [n for n in handler.args.args if n.arg == 'payload']
    if len(decorators) != 1 or len(payload) != 1 or ast.unparse(payload[0].annotation) != 'DeleteTweetRequest':
        raise ValueError('delete_twitter HTTP method or request type changed')
    if not any(k.arg == 'response_model' and ast.unparse(k.value) == 'ApiResponse' for k in decorators[0].keywords):
        raise ValueError('delete_twitter response model changed')
    classes = [n for n in schemas.body if isinstance(n, ast.ClassDef) and n.name == 'DeleteTweetRequest']
    if len(classes) != 1 or [ast.unparse(b) for b in classes[0].bases] != ['BaseModel']:
        raise ValueError('unsupported delete request class')
    properties = {}
    for field in classes[0].body:
        if isinstance(field, ast.AnnAssign):
            if not isinstance(field.target, ast.Name) or ast.unparse(field.annotation) != 'str' or not isinstance(field.value, ast.Call) or ast.unparse(field.value.func) != 'Field' or field.value.args:
                raise ValueError('unsupported request field declaration')
            constraints = {k.arg: ast.literal_eval(k.value) for k in field.value.keywords}
            if set(constraints) != {'min_length', 'max_length'}:
                raise ValueError('request field constraints changed')
            properties[field.target.id] = {'type': 'string', 'minLength': constraints['min_length'], 'maxLength': constraints['max_length']}
        elif isinstance(field, ast.FunctionDef):
            expected = ast.parse('''@field_validator("tweet_id", mode="before")
@classmethod
def normalize_tweet_id(cls, value: str) -> str:
    return value.strip()
''').body[0]
            if ast.dump(field) != ast.dump(expected):
                raise ValueError('unrepresented request validator changed')
        else:
            raise ValueError('unrepresented request class behavior')
    if set(properties) != {'aisa_api_key', 'tweet_id'}:
        raise ValueError('delete request fields changed; review the contract')
    properties['tweet_id']['description'] = 'The service strips surrounding whitespace before validating the length.'
    properties['tweet_id']['x-aisa-normalization'] = 'strip'
    properties['aisa_api_key']['description'] = 'AIsa API key bound to the OAuth account; the wrapper requires this body field in addition to gateway authorization.'
    document = {'openapi': '3.1.0', 'info': {'title': 'AIsa Twitter delete wrapper', 'version': REVISION}, 'paths': {
        '/delete_twitter': {'post': {'summary': 'Delete an authorized account tweet', 'requestBody': {
            'required': True, 'content': {'application/json': {'schema': {'type': 'object', 'properties': properties, 'required': list(properties)}}}},
            'responses': {'200': {'description': 'ApiResponse returned by the owning service; result data is not inferred.'}}}}}}
    return document, {'converter': VERSION, 'source_revision': REVISION, 'source_pages': [
        {'url': url, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}
        for url, raw in [(REFERENCE_URL, routes_raw), (SCHEMA_URL, schemas_raw)]]}


def import_reference(fetch):
    return convert_reference(fetch(REFERENCE_URL), fetch(SCHEMA_URL))
