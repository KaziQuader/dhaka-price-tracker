"""Gzipped raw snapshots on disk (spec §2 "Raw snapshots").

Layout: <data_dir>/raw/<source>/<YYYY-MM-DD>/<HHMMSS>_<slug>.gz, dated in Dhaka time.
If a site changes its HTML, the parser breaks but these files keep the history, and
`make reparse` can parse them again after the fix.
"""

import gzip
import re
from datetime import datetime
from pathlib import Path

from tracker.core.timeutil import to_dhaka

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class RawStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def save(self, source: str, slug: str, content: bytes, fetched_at: datetime) -> str:
        """Write the snapshot and return its path relative to the working directory."""
        local = to_dhaka(fetched_at)
        folder = self.data_dir / "raw" / source / local.date().isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{local:%H%M%S}_{_UNSAFE.sub('-', slug).strip('-') or 'page'}"
        path = folder / f"{stem}.gz"
        n = 2
        while path.exists():  # two fetches in the same second with the same slug
            path = folder / f"{stem}-{n}.gz"
            n += 1
        path.write_bytes(gzip.compress(content))
        return path.as_posix()

    @staticmethod
    def load(raw_path: str | Path) -> bytes:
        return gzip.decompress(Path(raw_path).read_bytes())
