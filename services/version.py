"""Content fingerprint of the deployed Python implementation for frozen analyses."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@lru_cache(maxsize=1)
def code_version() -> str:
    """Hash sorted relative paths and exact file bytes once per process."""
    root = Path(__file__).resolve().parents[1]
    files = sorted(
        (path for folder in ("domain/graph", "services", "ingest")
         for path in (root / folder).rglob("*.py")),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    digest = sha256()
    for path in files:
        name = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()
