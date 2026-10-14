# Text-to-SQL Assistant: project spec

A portfolio project. A Python assistant that turns natural-language questions into safe, read-only SQL
over the TPC-H schema, using schema retrieval (FAISS) plus Claude for generation, and measured with an
execution-accuracy eval. It is v2 of a Dify + Snowflake prototype (see `docs/prototype.md`).

## Hard rules

- **Never commit `prototype/`.** It holds the original Dify exports, which contain hardcoded credentials,
  and it is gitignored. Only `prototype-sanitized/` is published. `scripts/check_sanitized.py` (CI)
  fails if a sanitized file has a non-placeholder password condition, a Dify user UUID, or a dataset ID.
- **No secrets in the repo.** Keys come from `.env` (gitignored); `.env.example` lists the names only.
- **Ask before adding a dependency.** The approved list is in "Dependencies" below.
- **Tests must run with no API keys and no network**: fake LLM client, hash embedder, local DuckDB.
- Commits use `233865097+sainithya-2001@users.noreply.github.com` (set in the repo's local git config).
  Push to `github.com/sainithya-2001/text-to-sql-assistant` only when the owner says so.
- Paid API runs (the eval) need the owner's go-ahead and stay under a **$1 total cap**, enforced in code.

## Architecture

```
question
  -> SchemaRetriever (FAISS over table + column docs) -> top-k tables (+ FK-neighbour expansion)
  -> SqlGenerator (Claude, schema snippet in system prompt)          [full-schema mode skips retrieval]
  -> SqlGuard (sqlglot: parse, single statement, SELECT/WITH only, no DDL/DML/PRAGMA/COPY/ATTACH,
               inject LIMIT if missing)
  -> Executor (read-only connection, row cap, timeout)
       error? -> one self-correction retry: re-prompt with the SQL + DB error, back through SqlGuard
  -> Result (sql, columns, rows, attempts, token usage, cost)
```

## Layout

```
src/text_to_sql/
  config.py        settings from env (.env via python-dotenv): backend, model, limits, paths
  db/
    base.py        Backend protocol: execute(sql, max_rows, timeout_s) -> QueryResult; catalog()
    duckdb_backend.py   creates data/tpch.duckdb with `CALL dbgen(sf=0.01)`; opens it read_only=True
    snowflake_backend.py  optional; SNOWFLAKE_SAMPLE_DATA.TPCH_SF1; enabled only if SNOWFLAKE_* set
  schema/
    catalog.py     table/column metadata from the backend + hand-written TPC-H descriptions
    descriptions.py  business descriptions for the 8 TPC-H tables and their columns
    embed.py       Embedder protocol; HashEmbedder (tests/CI, offline); FastEmbedder (bge-small)
    retriever.py   hybrid retrieval: 0.7 x FAISS (IndexFlatIP, doc-per-table + doc-per-column, columns roll
                   up to their table) + 0.3 x keyword (table name/alias hit + description overlap), the
                   prototype's weighting; top-k then FK join-path bridging
  llm/
    client.py      thin wrapper over anthropic.Anthropic; FakeLLM for tests
    prompts.py     system prompt (ported from the prototype's SQL-writer rules) + repair prompt
    cost.py        price table, usage -> dollars (incl. cache read/write), BudgetGuard
  safety/guard.py  sqlglot validation + LIMIT injection
  pipeline.py      Assistant.ask(question, schema_mode="retrieved"|"full") -> Answer
  cli.py           `t2s ask "..."`, `t2s init-db`, `t2s schema`, `t2s eval ...`
app/streamlit_app.py  minimal UI: question box, toggles (model, schema mode), SQL + table + cost
glossary.yaml      business terms, synonyms, definitions, SQL; ambiguous terms with interpretations
eval/
  questions.yaml   40 items: id, difficulty (easy/medium/hard), question, gold_sql, order_matters
  glossary_questions.yaml   12 items using undefined business terms
  ambiguous_questions.yaml  8 items: 5 should get a clarifying question, 3 have a cue and should answer
  run_eval.py      runs configs, compares result sets, writes eval/results/*.json + summary.md
tests/             pytest, offline
prototype-sanitized/  sanitized Dify exports (v1..v4)
docs/              prototype.md, architecture diagram
```

## Key behaviours

- **DuckDB**: `INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01)` (~10 MB, no download beyond the extension).
  Queries run on a connection opened with `read_only=True`. Timeout is a `threading.Timer` that calls
  `con.interrupt()`. Row cap: fetch `max_rows + 1` and flag truncation.
- **Snowflake (optional)**: same TPC-H tables at `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1` (a shared, read-only
  database). Off unless `SNOWFLAKE_ACCOUNT/USER/PASSWORD/WAREHOUSE` are in `.env`. Uses
  `STATEMENT_TIMEOUT_IN_SECONDS`. SQL dialect switches via sqlglot (`duckdb` vs `snowflake`).
- **Guard** rejects: parse failures, more than one statement, any root that isn't `Select`/`Union`/
  `Intersect`/`Except`/`With`-wrapping-a-select, and any `Insert/Update/Delete/Merge/Create/Drop/Alter/
  Command/Copy/Pragma/Attach/Set` node anywhere in the tree. Read-only connection is the second layer.
- **Generation**: Claude must output SQL only (we still strip fences defensively). If the retrieved schema
  cannot answer the question, the model replies `CANNOT_ANSWER: <reason>` instead of guessing (the
  prototype's "no context, no SQL" rule).
- **Guard allowlists, not just denylists**: every table reference must be a plain identifier naming a
  catalog table or a CTE, which rejects table functions (`read_csv`, `duckdb_settings()`, `query()`),
  quoted file paths and system schemas. Scalar system functions (`getenv`, `current_setting`,
  `version()` -> `CURRENT_VERSION`) are denied by name.
- **Self-correction**: exactly one retry with the failed SQL and error text, for *fixable* failures
  (parse error, unknown table/column, DB error, timeout). Policy violations (writes, system access) are
  `blocked` immediately and never handed back to the model to "fix".
- **Prompt caching**: `cache_control` on the system block **only in full-schema mode**. Retrieved schemas
  differ per question, so caching them pays the 1.25x write premium for nothing. Measured (Sonnet 5.5):
  full-schema 3.2K-token prompt costs $0.0099 on the cache write, $0.0024 on a cache read.

- **Glossary** (`glossary.yaml`, `schema/glossary.py`): phrase match on word stems (numbers ignored, longest
  phrase wins). Matched terms add their tables to the retrieved set and their definitions to the *user*
  turn (the system prompt must stay byte-identical for caching). Ambiguous terms list interpretations
  with cue words; with no cue and no `choices`, `ask()` returns a `Clarification` without calling the
  model. With the glossary on, the model may also reply `CLARIFY: ...`. Glossary off == Phase 4 pipeline.

## Models and cost

| Model | ID | $/MTok in | $/MTok out | cache read |
|---|---|---|---|---|
| Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 | 0.20 |

- Default app model: `claude-sonnet-5-5` (overridable with `T2S_MODEL` / `--model`).
- Both models think adaptively by default; set `output_config.effort="low"` for SQL generation and keep
  `max_tokens` modest. No `temperature` (non-default sampling is rejected on these models).
- Check `stop_reason`: `refusal` and `max_tokens` become a failed attempt with a clear message.
- `BudgetGuard` tracks dollars from `response.usage` (`input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`) and refuses the next call once
  spent + projected cost of the next call would exceed the cap (default $1.00 for the eval).
- Estimated eval cost: 40 questions x 2 schema modes x 2 models = 160 calls (+ retries). Smoke test on
  Sonnet 5.5 at low effort: ~$0.005/question retrieved, ~$0.0024 full (cached), so Sonnet ~$0.30 and
  Haiku ~$0.02. The run starts with a 3-question pilot and extrapolates.

## Eval

- 40 questions over TPC-H: 14 easy (single table, filter/aggregate), 14 medium (2-3 table joins,
  group by/having), 12 hard (4+ joins, subqueries, windows, TPC-H-style analytics).
- Gold SQL is checked into `eval/questions.yaml` and verified by a test that runs every gold query.
- No ties at a "top N" cutoff: a test checks that the gold query's Nth and (N+1)th rows differ on the
  ordering key, otherwise equally-correct queries return different rows (seen in the smoke test).
- **Execution accuracy**: predicted and gold result sets match as multisets of rows (or as ordered lists
  when `order_matters`), after normalizing floats (round to 2 dp), Decimals, dates and NULLs. Column
  names and column order are ignored, but the column count must match.
- Matrix: {full schema, retrieved schema} x {Haiku, Sonnet}. Report accuracy by difficulty, retrieval
  recall (gold tables contained in retrieved tables), retries used, tokens, and dollars.
- Raw per-question results go in `eval/results/`; the README table is generated from the summary.

## Dependencies

Runtime: `anthropic`, `duckdb`, `sqlglot`, `faiss-cpu`, `numpy`, `python-dotenv`, `pyyaml`.
Extras: `[ui]` `streamlit`; `[snowflake]` `snowflake-connector-python`; `[embed]` `fastembed`
(BAAI/bge-small-en-v1.5, ONNX, ~70 MB model fetched on first use). Dev: `pytest`, `ruff`.
Everything else must be approved first.

## Commands

```
python -m venv .venv && .venv\Scripts\activate      # Windows (source .venv/bin/activate elsewhere)
pip install -e ".[dev]"
t2s init-db                       # build data/tpch.duckdb
t2s ask "top 5 customers by revenue in 1995"
pytest -q && ruff check .
python eval/run_eval.py --pilot 3 # then a full run with the owner's go-ahead
streamlit run app/streamlit_app.py
```

## Phases

0. Secret scan + sanitized prototype copies + this spec  (done)
1. DB layer (DuckDB TPC-H, optional Snowflake) + catalog/descriptions
2. Schema RAG (embedder, FAISS retriever) + Claude generator
3. Safety guard, executor limits, self-correction
4. Eval set (40 Qs + gold SQL) + runner + cost cap; run with approval
5. Business glossary: `glossary.yaml` of TPC-H business terms (e.g. revenue = extendedprice*(1-discount),
   "large order", "late shipment", regions/segments) retrieved alongside schema; ambiguous questions get a
   clarifying question instead of a guess; glossary + ambiguity items added to the eval
6. CLI + Streamlit
7. Tests, CI (GitHub Actions: ruff, pytest, sanitized check, `docker build` since Docker isn't available
   locally), Dockerfile, README (diagram, story, results)
