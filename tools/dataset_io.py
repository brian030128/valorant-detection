"""Checksum verification and path-checked archive extraction for training data."""
import hashlib
import zipfile

def verify(path,expected):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):digest.update(block)
    if digest.hexdigest()!=expected:raise RuntimeError(f'Checksum mismatch: {path.name}')

def extract(archive,destination):
    destination=destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            if not (destination/entry.filename).resolve().is_relative_to(destination):
                raise ValueError('Unsafe archive path')
        bundle.extractall(destination)
