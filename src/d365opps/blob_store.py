from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from d365opps.config import get_settings


@dataclass(slots=True)
class BlobReference:
    path: str
    checksum: str
    size: int


class LocalBlobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().blob_root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, source_name: str, external_id: str, payload: bytes, suffix: str) -> BlobReference:
        checksum = hashlib.sha256(payload).hexdigest()
        safe_source = source_name.replace(" ", "_").lower()
        safe_external = "".join(ch for ch in external_id if ch.isalnum() or ch in ("-", "_"))[:120]
        relative = Path(safe_source) / f"{safe_external}_{checksum[:16]}{suffix}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return BlobReference(path=str(relative), checksum=checksum, size=len(payload))

    def get_bytes(self, relative_path: str) -> bytes:
        return (self.root / relative_path).read_bytes()
