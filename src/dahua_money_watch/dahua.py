from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional, Union


DAV_TIME_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.(\d{2})")


@dataclass(frozen=True)
class DahuaClip:
    path: Path
    date: Optional[str]
    start_offset_s: int
    end_offset_s: int
    duration_s: int

    @property
    def start_clock(self) -> str:
        return seconds_to_clock(self.start_offset_s)

    def clock_at(self, offset_s: float) -> str:
        return seconds_to_clock(int(round(self.start_offset_s + offset_s)))


def seconds_to_clock(seconds: int) -> str:
    seconds = seconds % 86400
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_dahua_clip(path: Union[str, Path]) -> Optional[DahuaClip]:
    p = Path(path)
    match = DAV_TIME_RE.search(p.name)
    if not match:
        return None
    h1, m1, s1, h2, m2, s2 = map(int, match.groups())
    start = h1 * 3600 + m1 * 60 + s1
    end = h2 * 3600 + m2 * 60 + s2
    duration = end - start
    if duration < 0:
        duration += 86400
    date = next((part for part in p.parts if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part)), None)
    return DahuaClip(path=p, date=date, start_offset_s=start, end_offset_s=end, duration_s=duration)


def is_stable_file(path: Path, min_age_seconds: int) -> bool:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False
    return time.time() - stat.st_mtime >= min_age_seconds and stat.st_size > 0


def iter_dav_files(
    archive_root: Path,
    pattern: str,
    date: Optional[str],
    min_age_seconds: int,
) -> Iterable[Path]:
    if date:
        base = archive_root / date
        date_pattern = pattern[2:] if pattern.startswith("*/") else pattern
        iterator = base.glob(date_pattern)
    else:
        iterator = archive_root.glob(pattern)
    for path in sorted(iterator):
        if path.suffix.lower() != ".dav":
            continue
        if is_stable_file(path, min_age_seconds):
            yield path
