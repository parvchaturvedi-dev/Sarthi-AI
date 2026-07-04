"""Find the file the user is talking about — a path in the text, or by name.

Voice/text users rarely paste a full path; they say "Downloads me resume.pdf" or
"wo photo jo abhi aayi". This resolves such references to a real path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

HOME = Path.home()
COMMON_DIRS = [
    HOME / "Desktop",
    HOME / "Documents",
    HOME / "Downloads",
    HOME / "Pictures",
    HOME / "OneDrive" / "Desktop",
    HOME / "OneDrive" / "Documents",
    HOME / "OneDrive" / "Pictures",
    HOME / "OneDrive",
]

_RECENT = re.compile(r"\b(latest|recent|abhi|newest|last|just|jo abhi|aakhri)\b", re.I)


def _quoted_or_pathlike(text: str, exts) -> Optional[str]:
    """Pull an explicit path/filename with a matching extension out of the text."""
    ext_group = "|".join(e.lstrip(".") for e in exts)
    # a full-ish path or a bare filename ending in one of the extensions
    m = re.search(rf"([A-Za-z]:\\[^\"'<>|]+?\.(?:{ext_group}))", text, re.I)
    if m and Path(m.group(1)).exists():
        return m.group(1)
    m = re.search(rf"([\w\-. ]+?\.(?:{ext_group}))", text, re.I)
    if m:
        cand = m.group(1).strip()
        if Path(cand).exists():
            return str(Path(cand).resolve())
        return cand                       # a bare name to search for below
    return None


def _newest(exts) -> Optional[str]:
    best, best_mtime = None, -1.0
    for d in COMMON_DIRS:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                try:
                    mt = p.stat().st_mtime
                except OSError:
                    continue
                if mt > best_mtime:
                    best, best_mtime = str(p), mt
    return best


def _search_by_name(name: str, exts) -> Optional[str]:
    stem = Path(name).stem.lower()
    for d in COMMON_DIRS:
        if not d.exists():
            continue
        # exact-ish first
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts and stem in p.stem.lower():
                return str(p)
    return None


def resolve_file(text: str, exts: List[str]) -> Optional[str]:
    """Return a real file path for the file referenced in `text`, or None.

    exts: allowed extensions incl. dot, e.g. ['.pdf'] or ['.jpg','.png',...].
    """
    exts = [e.lower() for e in exts]
    cand = _quoted_or_pathlike(text, exts)
    if cand:
        if os.path.isabs(cand) and Path(cand).exists():
            return cand
        found = _search_by_name(cand, exts)
        if found:
            return found
    if _RECENT.search(text):
        return _newest(exts)
    return None
