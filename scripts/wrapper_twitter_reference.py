"""Read the owning service's pinned Python declarations without importing its code."""
import ast
import hashlib
import re

REVISION = '9481772229feb96eed7fef509234d089cd0d7ec3'
ROOT = 'https://raw.githubusercontent.com/AIsa-team/AisaTwitterAuthService/' + REVISION + '/'
REFERENCE_URL = ROOT + 'app/api/routes/twitter.py'
SCHEMA_URL = ROOT + 'app/schemas/twitter.py'
VERSION = 'scripts/wrapper_twitter_reference.py@3'


def response_reference(routes_raw, schemas_raw):
    """Project the explicit public response_model, including its typed opaque map.

    We never infer Twitter upstream result fields. ApiResponse intentionally
    declares data as an optional arbitrary dictionary; FastAPI serializes this
    model for these successful routes.
    """
    routes, schemas = ast.parse(routes_raw), ast.parse(schemas_raw)
    classes = [n for n in schemas.body if isinstance(n, ast.ClassDef) and n.name == 'ApiResponse']
    expected = ast.parse("""class ApiResponse(BaseModel):
    code: int
    msg: str
    data: Optional[dict[str, Any]] = None
""").body[0]
    if len(classes) != 1 or ast.dump(classes[0]) != ast.dump(expected):
        raise ValueError('ApiResponse declaration changed; response review required')
    schema = {'type': 'object', 'properties': {'code': {'type': 'integer'},
        'msg': {'type': 'string'}, 'data': {'anyOf': [{'type': 'object',
            'additionalProperties': True}, {'type': 'null'}], 'default': None,
            'description': 'The owning service explicitly declares an optional dictionary of arbitrary values; nested Twitter result fields are opaque.'}},
        'required': ['code', 'msg']}
    paths = {}
    for route in ('/delete_twitter', '/post_twitter'):
        matches = []
        for handler in routes.body:
            if not isinstance(handler, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in handler.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                    try:
                        path = ast.literal_eval(dec.args[0])
                    except ValueError:
                        continue
                    if path == route:
                        matches.append((handler, dec))
        if route == '/post_twitter' and not matches:
            continue  # A focused delete-only source fixture need not invent post.
        if len(matches) != 1 or ast.unparse(matches[0][1].func) != 'router.post':
            raise ValueError('owning response route method changed')
        for keyword in matches[0][1].keywords:
            if keyword.arg == 'status_code' and ast.literal_eval(keyword.value) == 200:
                continue
            if keyword.arg != 'response_model':
                raise ValueError('owning response serialization/status changed')
        if not any(k.arg == 'response_model' and ast.unparse(k.value) == 'ApiResponse' for k in matches[0][1].keywords):
            raise ValueError('owning response_model changed')
        paths[route] = {'post': {'responses': {'200': {'description': 'Successful ApiResponse serialized by the owning service.',
            'content': {'application/json': {'schema': schema}}}}}}
    return paths


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
    normalized_bounds = {key: properties['tweet_id'].pop(key) for key in ('minLength', 'maxLength')}
    properties['tweet_id']['x-aisa-normalized-schema'] = {'type': 'string', **normalized_bounds}
    properties['tweet_id']['description'] = 'The service strips surrounding whitespace first; the result must contain 1 to 64 characters. Length limits apply after normalization, not to the raw input.'
    properties['tweet_id']['x-aisa-normalization'] = 'strip'
    properties['aisa_api_key']['description'] = 'AIsa API key bound to the OAuth account; the wrapper requires this body field in addition to gateway authorization.'
    document = {'openapi': '3.1.0', 'info': {'title': 'AIsa Twitter delete wrapper', 'version': REVISION}, 'paths': {
        '/delete_twitter': {'post': {'summary': 'Delete an authorized account tweet', 'requestBody': {
            'required': True, 'content': {'application/json': {'schema': {'type': 'object', 'properties': properties, 'required': list(properties)}}}},
            'responses': {'200': {'description': 'ApiResponse returned by the owning service; result data is not inferred.'}}}}}}
    for path, item in response_reference(routes_raw, schemas_raw).items():
        if path in document['paths']:
            document['paths'][path]['post']['responses'] = item['post']['responses']
        # Post has a multipart/JSON parser outside this request converter. Its
        # response declaration is available through response_reference only;
        # adding it here would falsely assert a complete request source.
    return document, {'converter': VERSION, 'source_revision': REVISION, 'refresh_policy': 'pinned', 'refresh_reason': 'Private owning-service source; revision updates require an authorized reader.', 'source_pages': [
        {'url': url, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}
        for url, raw in [(REFERENCE_URL, routes_raw), (SCHEMA_URL, schemas_raw)]]}


def import_reference(fetch):
    return convert_reference(fetch(REFERENCE_URL), fetch(SCHEMA_URL))


def convert_response_only_reference(routes_raw, schemas_raw, upstream_origin_sha256):
    """Prepare post response evidence with an independently reviewed origin pin.

    The source defines the owning route, not the deployment hostname. The origin
    pin must come from a reviewed current binding; credentials/hosts stay private.
    This helper never fetches, registers or approves a source.
    """
    if not isinstance(upstream_origin_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', upstream_origin_sha256):
        raise ValueError('reviewed Twitter origin SHA256 required')
    responses = response_reference(routes_raw, schemas_raw)
    if '/post_twitter' not in responses:
        raise ValueError('owning post response route missing')
    document = {'openapi': '3.1.0', 'info': {'title': 'Twitter post response declaration', 'version': REVISION},
        'servers': [{'url': 'https://api.aisa.one'}],
        'paths': {'/apis/v1/twitter/post_twitter': responses['/post_twitter']}}
    return document, {'kind': 'manual', 'converter': VERSION, 'response_only': True,
        'path_space': 'public', 'source_revision': REVISION, 'refresh_policy': 'pinned',
        'upstream_path_sha256': hashlib.sha256(b'/post_twitter').hexdigest(),
        'upstream_origin_sha256': upstream_origin_sha256,
        'source_pages': [{'url': url, 'raw_content_hash': 'sha256:' + hashlib.sha256(raw).hexdigest()}
            for url, raw in [(REFERENCE_URL, routes_raw), (SCHEMA_URL, schemas_raw)]]}
