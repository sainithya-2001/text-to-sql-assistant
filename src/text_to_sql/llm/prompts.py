"""Prompts. The SQL rules are carried over from the prototype's Dify "SQL writer" node (see
docs/prototype.md), minus the Snowflake-only and upper-case-everything rules."""

from __future__ import annotations

CANNOT_ANSWER = "CANNOT_ANSWER"
CLARIFY = "CLARIFY"

DIALECT_NOTES = {
    "duckdb": "DuckDB SQL. Dates: DATE '1995-01-01', EXTRACT(YEAR FROM d), date_trunc('month', d), "
    "d + INTERVAL 3 MONTH. String concat with ||.",
    "snowflake": "Snowflake SQL. Dates: DATE '1995-01-01', YEAR(d), DATE_TRUNC('MONTH', d), "
    "DATEADD(MONTH, 3, d).",
}

SYSTEM_TEMPLATE = """You translate questions about a business database into one read-only SQL query.

Dialect: {dialect_notes}

Database schema (the only tables and columns you may use):

{schema}

Rules:
- Write exactly one SELECT statement (CTEs with WITH are fine). Never write INSERT, UPDATE, DELETE,
  MERGE, DDL, COPY, PRAGMA, SET or ATTACH.
- Use only tables and columns listed above. Never invent a column; if the schema cannot answer the
  question, reply with `{cannot}: <one-sentence reason>` and nothing else.
- Use explicit ANSI JOIN ... ON with the join keys shown; no comma joins.
- Return the columns the question asks for, with readable aliases. Add ORDER BY when the question
  implies ranking or "top N", and LIMIT for "top N".
- Coded values (flags, statuses, segments, names) are stored exactly as described in the schema
  comments; match them literally (e.g. r_name = 'EUROPE').
- Prefer exact arithmetic on the given columns; don't round unless asked.

Output only the SQL. No explanation, no comments, no markdown fences."""

# Per-question glossary definitions go in the user turn, not the system prompt, so the system prompt
# stays byte-identical across questions and full-schema prompt caching keeps working.
GLOSSARY_USER_TEMPLATE = """Business definitions for this question (use them exactly):
{terms}

Question: {question}"""

CLARIFY_SECTION = """

If the question uses a business term or criterion that is not defined above and has several reasonable
meanings that would give different results, reply with `{clarify}: <one short question to the user>`
and nothing else. Do not ask when one reading is clearly intended or the schema comments settle it."""

REPAIR_TEMPLATE = """Your previous query failed.

Question: {question}

Query:
{sql}

Error:
{error}

Write a corrected query that follows the same rules. Output only the SQL."""


def system_prompt(schema_text: str, dialect: str, *, allow_clarify: bool = False) -> str:
    out = SYSTEM_TEMPLATE.format(
        dialect_notes=DIALECT_NOTES.get(dialect, dialect), schema=schema_text, cannot=CANNOT_ANSWER
    )
    if allow_clarify:
        out += CLARIFY_SECTION.format(clarify=CLARIFY)
    return out


def user_message(question: str, glossary_text: str = "") -> str:
    if not glossary_text:
        return question
    return GLOSSARY_USER_TEMPLATE.format(terms=glossary_text, question=question)


def repair_prompt(question: str, sql: str, error: str) -> str:
    return REPAIR_TEMPLATE.format(question=question, sql=sql, error=error[:2000])
