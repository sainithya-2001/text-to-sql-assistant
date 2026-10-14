"""Text embedders. All return L2-normalized float32 rows, so inner product == cosine similarity."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

import numpy as np

from ..config import PROJECT_ROOT


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(norms, 1e-12)


_WORD = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    """Deterministic bag-of-words + character-trigram hashing. Offline; used in tests and CI.

    Much weaker than a learned model (no synonyms), but stable and dependency-free.
    """

    name = "hash"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        words = _WORD.findall(text.lower().replace("_", " "))
        feats = [f"w:{w}" for w in words]
        for w in words:
            if len(w) > 4:
                feats.append(f"w:{w[:5]}")  # crude stem: shipped/shipping/ship -> "shipp"/"ship"
            padded = f"#{w}#"
            feats.extend(f"c:{padded[i : i + 3]}" for i in range(len(padded) - 2))
        return feats

    def _embed(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for f in self._features(text):
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            weight = 1.0 if f.startswith("w:") else 0.3
            v[h % self.dim] += weight if (h >> 63) & 1 else -weight
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack([self._embed(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])


class FastEmbedder:
    """BAAI/bge-small-en-v1.5 via fastembed (ONNX, CPU). Model (~70 MB) is downloaded on first use."""

    name = "fastembed"

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: Path | None = None):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            from fastembed import TextEmbedding
        except ImportError as e:  # pragma: no cover - optional extra
            raise RuntimeError('fastembed is not installed: pip install -e ".[embed]"') from e
        cache_dir = cache_dir or Path(os.environ.get("T2S_MODEL_CACHE", PROJECT_ROOT / "data" / "models"))
        self._model = TextEmbedding(model_name, cache_dir=str(cache_dir))
        self.name = f"fastembed:{model_name}"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack(list(self._model.passage_embed(texts))))

    def embed_query(self, text: str) -> np.ndarray:
        # query_embed adds bge's retrieval instruction prefix
        return _normalize(np.stack(list(self._model.query_embed([text]))))


def make_embedder(kind: str) -> Embedder:
    if kind == "hash":
        return HashEmbedder()
    if kind == "fastembed":
        return FastEmbedder()
    raise ValueError(f"unknown embedder {kind!r} (expected 'fastembed' or 'hash')")
