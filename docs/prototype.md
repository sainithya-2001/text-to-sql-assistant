# Prototype (v1): Dify + Snowflake

The first version of this assistant was a low-code [Dify](https://dify.ai) "advanced-chat" workflow
wired to a Snowflake `ECOMMERCE.E_SCHEMA` database. Four exports from Nov 2025 are kept, sanitized,
in [`prototype-sanitized/`](../prototype-sanitized/) (credentials, user identifiers and knowledge-base
IDs replaced with `<PLACEHOLDERS>`).

| File | Date | What changed |
|---|---|---|
| `v1_user_id_classifier.yml` | Nov 10 | No login. An LLM classifier routes on `sys.user_id` + "is it a SELECT?" |
| `v2_login_gate_llm_router.yml` | Nov 13 | Username/password start form, IF/ELSE login gate, LLM classifier routes per user |
| `v3_select_classifier_ifelse_router.yml` | Nov 15 | Classifier only judges SELECT vs DML; per-user routing moved to a deterministic IF/ELSE |
| `v4_final_double_gate.yml` | Nov 15 | Login checked up front *and* again before execution; stronger result-parsing code node |

## Flow (v4, final)

```
Start (Login_ID, Login_password)
  -> IF/ELSE login gate ----------------------- fail -> "Invalid login credentials"
  -> Knowledge Retrieval (Dify KB of table/column docs; hybrid: 0.7 vector + 0.3 keyword, top_k=4,
                          OpenAI text-embedding-3-large)
  -> LLM "SQL writer" (gemini-2.5-flash, temp 0.7)
  -> Question classifier (gpt-4o-mini): "contains UPDATE/DELETE/ALTER" vs "only SELECT"
        DML -> "You are trying to manipulate the data, it's not allowed."
  -> IF/ELSE per-user router -> one of 3 Snowflake SQL tool nodes (one per role/connection)
  -> Code node: merge the 3 branch outputs, unwrap Dify `{"data": [...]}` envelopes,
                empty -> "Access Denied"
  -> LLM "answer writer" (gemini-2.5-flash): turn JSON rows into a direct answer
  -> Answer
```

## Prompts worth keeping

**SQL writer (system)**, paraphrased and with typos fixed:
- Convert the question into a single, syntactically correct Snowflake SQL query.
- Infer tables/columns only from the retrieved context; if the context is empty, say no objects
  were found and **do not produce SQL** (anti-hallucination).
- Fully qualify every table (`DB.SCHEMA.TABLE`); use ANSI JOINs, no implicit joins.
- Use aggregation, window functions, subqueries where relevant; Snowflake date functions.
- Case-insensitive string filters (`UPPER(col) = UPPER('value')`).
- Quote identifiers only when required; end with a semicolon.
- Output only SQL: no prose, no markdown fences.

**Answer writer (system)**: given the query result JSON, answer only the question asked; if the
result is empty say so; if it contains an error, show the error; don't invent values; offer to
explain extra columns rather than summarizing them.

## What v2 keeps, and what it fixes

| Prototype | Problem | v2 |
|---|---|---|
| Retrieval over a hand-built KB of schema docs | Good idea | Keep: FAISS over table/column descriptions generated from the live catalog |
| "Output only SQL" + "no context, no SQL" rules | Good idea | Keep in the generation prompt |
| LLM classifier decides if SQL is safe | Non-deterministic; a prompt can talk its way past it | `sqlglot` AST check: single statement, `SELECT`/`WITH` only, plus a read-only connection |
| Passwords hardcoded in IF/ELSE nodes | Credentials in the workflow file | No in-app auth; all credentials come from `.env` |
| Per-user routing duplicates the SQL tool 3x | Duplication; access control in the app layer | One executor; access control belongs to database roles |
| temperature 0.7 for SQL | High-variance SQL | Current Claude models fix sampling; low effort + a strict "SQL only" output contract |
| No error recovery | One bad column name = dead end | One self-correction retry with the DB error message |
| No measurement | "Seems to work" | 40-question eval with execution accuracy |
