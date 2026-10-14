"""Schema retrieval: hybrid (vector + keyword) search over table and column descriptions.

Each table contributes one table-level document and one document per column. The vector half is FAISS
inner-product search; a table's vector score is the best of its table doc and the mean of its top two
column docs. The keyword half rewards questions that name a table's entity ("orders", "country") or
share words with its descriptions. Scores are mixed 0.7/0.3, the same weighting the Dify prototype's
hybrid retrieval used. The top-k tables are then closed over the FK graph so the model always gets a
joinable set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import faiss
import numpy as np

from . import descriptions
from .catalog import Catalog
from .embed import Embedder

STOPWORDS = set(
    "a an the of in on for to by and or with without from per each every all any what which who whom "
    "whose how many much is are was were be been do does did have has had that this these those than "
    "then there their them they it its as at into over under between most least more less top show "
    "list give find get me us our we you your i number count total average avg sum max min".split()
)
_WORD = re.compile(r"[a-z]+")


def stem(word: str) -> str:
    for suffix, repl in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + repl
    return word


def keywords(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text.lower().replace("_", " ")) if w not in STOPWORDS}


@dataclass(frozen=True)
class SchemaDoc:
    table: str
    column: str | None
    text: str


@dataclass
class Retrieval:
    tables: list[str]  # final set given to the model (top-k + join bridges), sorted
    ranked: list[tuple[str, float]]  # every table with its hybrid score, best first
    bridges: list[str] = field(default_factory=list)  # tables added only to connect joins


def build_docs(catalog: Catalog) -> list[SchemaDoc]:
    docs = []
    for t in catalog.tables.values():
        col_names = ", ".join(c.name for c in t.columns)
        docs.append(SchemaDoc(t.name, None, f"table {t.name}: {t.description} Columns: {col_names}"))
        for c in t.columns:
            docs.append(SchemaDoc(t.name, c.name, f"{t.name}.{c.name} ({t.name}): {c.description}"))
    return docs


class SchemaRetriever:
    def __init__(
        self,
        catalog: Catalog,
        embedder: Embedder,
        *,
        vector_weight: float = 0.7,
        column_weight: float = 0.9,
    ):
        self.catalog = catalog
        self.embedder = embedder
        self.vector_weight = vector_weight
        self.column_weight = column_weight
        self.docs = build_docs(catalog)
        vectors = embedder.embed_documents([d.text for d in self.docs])
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

        self._names: dict[str, set[str]] = {}
        self._vocab: dict[str, set[str]] = {}
        for t in catalog.tables.values():
            aliases = descriptions.TABLE_ALIASES.get(t.name, [])
            self._names[t.name] = {stem(t.name)} | {stem(a) for a in aliases}
            text = " ".join([t.description] + [c.description for c in t.columns])
            self._vocab[t.name] = keywords(text)

    def vector_scores(self, question: str) -> dict[str, float]:
        q = self.embedder.embed_query(question)
        sims, ids = self.index.search(q, len(self.docs))
        best: dict[str, float] = {}
        col_hits: dict[str, list[float]] = {}
        for sim, i in zip(sims[0], ids[0], strict=True):
            doc = self.docs[int(i)]
            if doc.column is None:
                best[doc.table] = max(best.get(doc.table, -1.0), float(sim))
            else:
                col_hits.setdefault(doc.table, []).append(float(sim))
        for table, hits in col_hits.items():
            top = sorted(hits, reverse=True)[:2]
            best[table] = max(best.get(table, -1.0), self.column_weight * float(np.mean(top)))
        return best

    def keyword_scores(self, question: str) -> dict[str, float]:
        q = keywords(question)
        if not q:
            return {t: 0.0 for t in self.catalog.tables}
        out = {}
        for t in self.catalog.tables:
            name_hit = 1.0 if q & self._names[t] else 0.0
            overlap = len(q & self._vocab[t]) / len(q)
            out[t] = 0.7 * name_hit + 0.3 * overlap
        return out

    def score_tables(self, question: str) -> list[tuple[str, float]]:
        vec = self.vector_scores(question)
        kw = self.keyword_scores(question)
        w = self.vector_weight
        scores = {t: w * vec.get(t, 0.0) + (1 - w) * kw.get(t, 0.0) for t in self.catalog.tables}
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))

    def retrieve(self, question: str, k: int = 4) -> Retrieval:
        ranked = self.score_tables(question)
        chosen = {t for t, _ in ranked[:k]}
        joined = self.catalog.join_path(chosen)
        return Retrieval(tables=sorted(joined), ranked=ranked, bridges=sorted(joined - chosen))
