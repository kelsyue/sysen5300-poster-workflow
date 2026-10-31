"""Validated checkpoints, scoped to the source PDF, candidate and generation code."""
import hashlib
import json
import shutil
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StageCache:
    def __init__(self, root, identity):
        self.root = Path(root)
        self.identity = identity
        self.key = digest(identity)

    def directory(self, stage, inputs):
        return self.root / self.key / f'{stage}-{digest(inputs)}'

    def load(self, stage, inputs, destination=None):
        folder = self.directory(stage, inputs)
        manifest = folder / 'checkpoint.json'
        if not manifest.exists():
            return None
        data = json.loads(manifest.read_text())
        if data['identity'] != self.identity:
            raise ValueError('Checkpoint identity mismatch')
        # Validate every saved artifact before restoring any of them.
        for rel, expected in data['files'].items():
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise ValueError('Unsafe checkpoint path')
            if file_digest(folder / 'files' / rel) != expected:
                raise ValueError(f'Checkpoint artifact changed: {rel}')
        if destination is not None:
            for rel in data['files']:
                target = Path(destination) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / 'files' / rel, target)
        return data['payload']

    def save(self, stage, inputs, payload, source=None, files=()):
        folder = self.directory(stage, inputs)
        folder.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for rel in sorted(set(map(str, files))):
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise ValueError('Unsafe checkpoint path')
            target = folder / 'files' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(source) / rel, target)
            hashes[rel] = file_digest(target)
        temporary = folder / 'checkpoint.json.tmp'
        temporary.write_text(json.dumps({'identity': self.identity, 'files': hashes,
                                         'payload': payload}, indent=2))
        temporary.replace(folder / 'checkpoint.json')
