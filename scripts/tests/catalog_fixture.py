"""Read the immutable sanitized W0 catalog as test input, never publication."""
from functools import lru_cache
import hashlib
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory

ARCHIVE = Path(__file__).parent / 'fixtures/w0-package/scripts/api-contract-acceptance/data/full-catalog.tar.gz'
SHA256 = 'f2b35c81df49b3a31053f3b4e8978778e52556d2d36536c23f4d7f28f8e0f02f'
_directory = None


@lru_cache(maxsize=1)
def catalog_root():
    global _directory
    if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Frozen catalog test input hash mismatch')
    _directory = TemporaryDirectory(prefix='aisa-docs-test-catalog-')
    directory = Path(_directory.name)
    with tarfile.open(ARCHIVE) as archive:
        members = [member for member in archive.getmembers() if member.name.startswith('input/')]
        archive.extractall(directory, members=members, filter='data')
    root = directory / 'input'
    if len(list((root / 'openapi/upstream').glob('*.json'))) != 67:
        raise ValueError('Frozen test source inventory mismatch')
    return root
