"""Business glossary: map business terms in a question to definitions, tables, or a clarifying question."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .retriever import stem

_TOKEN = re.compile(r"[a-z0-9]+")


def stems(text: str) -> list[str]:
    return [stem(w) for w in _TOKEN.findall(text.lower().replace("-", " "))]


def _contains(haystack: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(haystack[i : i + n] == phrase for i in range(len(haystack) - n + 1))


@dataclass(frozen=True)
class Interpretation:
    label: str
    cues: tuple[str, ...]
    definition: str
    sql: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class Term:
    term: str
    synonyms: tuple[str, ...] = ()
    definition: str = ""
    sql: str = ""
    tables: tuple[str, ...] = ()
    clarify: str = ""
    interpretations: tuple[Interpretation, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return bool(self.interpretations)

    def phrases(self) -> list[list[str]]:
        return [stems(p) for p in (self.term, *self.synonyms)]


@dataclass(frozen=True)
class Resolved:
    """A matched term with the meaning that applies (for ambiguous terms, the chosen interpretation)."""

    term: str
    definition: str
    sql: str
    tables: tuple[str, ...]
    via: str = ""  # interpretation label, if any

    def render(self) -> str:
        label = f"{self.term} ({self.via})" if self.via else self.term
        return f"- {label}: {self.definition} SQL: {self.sql}"


@dataclass(frozen=True)
class Clarification:
    question: str
    term: str | None = None
    options: tuple[str, ...] = ()


@dataclass
class GlossaryMatch:
    resolved: list[Resolved] = field(default_factory=list)
    unresolved: list[Term] = field(default_factory=list)

    @property
    def tables(self) -> set[str]:
        return {t for r in self.resolved for t in r.tables}

    def clarification(self) -> Clarification | None:
        if not self.unresolved:
            return None
        t = self.unresolved[0]
        return Clarification(
            t.clarify or f"What do you mean by {t.term}?", t.term, tuple(i.label for i in t.interpretations)
        )

    def render(self) -> str:
        return "\n".join(r.render() for r in self.resolved)


class Glossary:
    def __init__(self, terms: list[Term]):
        self.terms = terms

    @classmethod
    def load(cls, path: Path) -> Glossary:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        terms = []
        for t in raw["terms"]:
            interps = tuple(
                Interpretation(
                    label=i["label"],
                    cues=tuple(str(c) for c in i.get("cues", [])),
                    definition=i["definition"],
                    sql=i["sql"],
                    tables=tuple(i.get("tables", [])),
                )
                for i in t.get("interpretations", [])
            )
            terms.append(
                Term(
                    term=t["term"],
                    synonyms=tuple(t.get("synonyms", [])),
                    definition=t.get("definition", ""),
                    sql=t.get("sql", ""),
                    tables=tuple(t.get("tables", [])),
                    clarify=t.get("clarify", ""),
                    interpretations=interps,
                )
            )
        return cls(terms)

    def match(self, question: str, choices: dict[str, str] | None = None) -> GlossaryMatch:
        """Find terms used in `question`.

        `choices` maps an ambiguous term to the interpretation label the user picked.
        Longer phrases win: "gross revenue" suppresses "revenue" when both match the same words.
        """
        q = stems(question)
        q_no_nums = [w for w in q if not w.isdigit()]  # "top 5 customers" matches "top customers"
        choices = {k.lower(): v for k, v in (choices or {}).items()}
        hits: list[tuple[Term, list[str]]] = []
        for t in self.terms:
            matched = [p for p in t.phrases() if _contains(q, p) or _contains(q_no_nums, p)]
            if matched:
                hits.append((t, max(matched, key=len)))
        # drop a term whose matched phrase is contained in a longer matched phrase of another term
        kept = [
            (t, p)
            for t, p in hits
            if not any(o is not t and len(op) > len(p) and _contains(op, p) for o, op in hits)
        ]
        out = GlossaryMatch()
        for t, _ in kept:
            if not t.ambiguous:
                out.resolved.append(Resolved(t.term, t.definition, t.sql, t.tables))
                continue
            pick = self._pick(t, q, choices.get(t.term.lower()))
            if pick is None:
                out.unresolved.append(t)
            else:
                out.resolved.append(Resolved(t.term, pick.definition, pick.sql, pick.tables, pick.label))
        return out

    @staticmethod
    def _pick(t: Term, q: list[str], choice: str | None) -> Interpretation | None:
        if choice:
            for i in t.interpretations:
                if i.label.lower() == choice.lower():
                    return i
            raise ValueError(
                f"{choice!r} is not an option for {t.term!r}: {[i.label for i in t.interpretations]}"
            )
        cued = [i for i in t.interpretations if any(_contains(q, stems(c)) for c in i.cues)]
        return cued[0] if len(cued) == 1 else None
