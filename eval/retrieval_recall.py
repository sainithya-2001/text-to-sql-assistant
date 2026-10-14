"""Offline retrieval analysis: does the schema given to the model contain every table the gold SQL uses?

No API calls; uses the real embedder. Run: python eval/retrieval_recall.py
"""

from __future__ import annotations

from text_to_sql.config import PROJECT_ROOT, Settings
from text_to_sql.db import open_backend
from text_to_sql.evaluation import gold_tables, load_questions
from text_to_sql.schema.catalog import Catalog
from text_to_sql.schema.embed import make_embedder
from text_to_sql.schema.glossary import Glossary
from text_to_sql.schema.retriever import SchemaRetriever

FILES = ["questions.yaml", "glossary_questions.yaml", "ambiguous_questions.yaml"]
KS = (3, 4, 5, 6)


def main() -> None:
    settings = Settings.from_env()
    backend = open_backend(settings)
    catalog = Catalog.from_backend(backend)
    embedder = make_embedder(settings.embedder)
    glossary = Glossary.load(settings.glossary_path)
    retriever = SchemaRetriever(catalog, embedder)
    items = [i for f in FILES for i in load_questions(PROJECT_ROOT / "eval" / f) if i.gold_sql]

    print("Retrieval recall: gold tables contained in the schema sent to the model.")
    print(
        f"{len(items)} questions with gold SQL; embedder={embedder.name}; hybrid retrieval + FK bridging.\n"
    )
    print("| Glossary tables | " + " | ".join(f"k={k}" for k in KS) + " |")
    print("|---|" + "---|" * len(KS))
    misses: dict[str, list[str]] = {}
    for use_gloss in (False, True):
        cells = []
        for k in KS:
            hit, sent = 0, 0
            for it in items:
                tables = set(retriever.retrieve(it.question, k).tables)
                if use_gloss:
                    m = glossary.match(it.question)
                    tables = catalog.join_path(tables | (m.tables & set(catalog.names())))
                ok = gold_tables(it.gold_sql) <= tables
                hit += ok
                sent += len(tables)
                if not ok:
                    misses.setdefault(f"k={k}, {'with' if use_gloss else 'no'} glossary", []).append(it.id)
            cells.append(
                f"{100 * hit / len(items):.0f}% ({hit}/{len(items)}), {sent / len(items):.1f} tables"
            )
        print(f"| {'yes' if use_gloss else 'no'} | " + " | ".join(cells) + " |")
    print("\nMisses:")
    for name, ids in misses.items():
        print(f"- {name}: {', '.join(ids)}")


if __name__ == "__main__":
    main()
