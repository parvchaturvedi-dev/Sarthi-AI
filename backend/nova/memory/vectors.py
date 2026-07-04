"""Tiny in-process vector utilities for semantic memory.

For the handful-to-a-few-hundred facts Nova remembers, a full vector DB
(FAISS/Chroma) is overkill. We store each embedding as a float32 BLOB in SQLite
and do cosine similarity in NumPy at query time — instant at this scale, zero
extra dependencies. The Memory interface stays the same; only recall gets smarter.
"""

from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple


def pack(vec: Sequence[float]) -> bytes:
    """Serialize a float vector to compact little-endian float32 bytes."""
    return struct.pack(f"<{len(vec)}f", *[float(x) for x in vec])


def unpack(blob: bytes) -> List[float]:
    """Inverse of pack()."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    import math

    if len(a) != len(b) or not a:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


def top_k(
    query: Sequence[float],
    items: Sequence[Tuple[str, Sequence[float]]],
    k: int = 6,
    min_score: float = 0.2,
) -> List[Tuple[str, float]]:
    """Rank (text, vector) pairs by cosine similarity to `query`.

    Uses NumPy when available (fast, vectorised); falls back to pure Python.
    Returns the top-k (text, score) above `min_score`, highest first.
    """
    if not items:
        return []
    scored: List[Tuple[str, float]]
    try:
        import numpy as np

        q = np.asarray(query, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        mat = np.asarray([v for _, v in items], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0] = 1e-9
        sims = (mat @ q) / (norms * qn)
        scored = [(items[i][0], float(sims[i])) for i in range(len(items))]
    except Exception:
        scored = [(text, _cosine(query, vec)) for text, vec in items]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [(text, s) for text, s in scored[:k] if s >= min_score]
