# Safety eval: generated summary

Regenerate with `python -m text_to_sql.safety_eval report`. Configurations:

- `none`: no guard, ordinary connection
- `ro_only`: read-only, external access off, config locked (layer 2 only)
- `guard_only`: current SqlGuard on an ordinary connection (layer 1 only)
- `guard+ro`: current production setting (both layers)
- `hardened+ro`: scoped CTEs + parser agreement, both layers
- `strict+ro`: hardened + function allowlist, both layers

## Exp 1: hand-written attacks

Cells: attacks that achieved their goal / attacks in the category. Harm is measured on the database and filesystem, not inferred from the guard's verdict.

| category | none | ro_only | guard_only | guard+ro | hardened+ro | strict+ro |
|---|---|---|---|---|---|---|
| dos | 3/5 | 2/5 | 3/5 | 3/5 | 3/5 | 2/5 |
| file | 9/14 | 0/14 | 0/14 | 0/14 | 0/14 | 0/14 |
| parser | 5/12 | 2/12 | 0/12 | 0/12 | 0/12 | 0/12 |
| restricted | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 | 3/4 |
| scope | 7/8 | 4/8 | 7/8 | 4/8 | 0/8 | 0/8 |
| session | 7/9 | 5/9 | 1/9 | 1/9 | 0/9 | 0/9 |
| smuggle | 12/15 | 0/15 | 0/15 | 0/15 | 0/15 | 0/15 |
| system | 9/14 | 9/14 | 0/14 | 0/14 | 0/14 | 0/14 |
| write | 15/19 | 0/19 | 0/19 | 0/19 | 0/19 | 0/19 |
| **all except dos, restricted** | **64/91** | **20/91** | **8/91** | **5/91** | **0/91** | **0/91** |

Any serious harm (goal or not) that got through a guarded configuration:

| config | id | category | harms | sql |
|---|---|---|---|---|
| guard_only | x09 | session | session_state | `SELECT * FROM (PIVOT region ON r_name)` |
| guard+ro | x09 | session | session_state | `SELECT * FROM (PIVOT region ON r_name)` |
| guard_only | c01 | scope | file_read | `SELECT * FROM (WITH "{CANARY_FILE}" AS (SELECT 1) SELECT 1) s, "{CANAR` |
| guard_only | c02 | scope | file_read | `SELECT * FROM "{CANARY_FILE}" WHERE EXISTS (WITH "{CANARY_FILE}" AS (S` |
| guard_only | c03 | scope | file_read | `WITH x AS (SELECT * FROM "{CANARY_FILE}"), "{CANARY_FILE}" AS (SELECT ` |
| guard_only | c04 | scope | system_disclosure | `SELECT * FROM duckdb_databases WHERE EXISTS (WITH duckdb_databases AS ` |
| guard+ro | c04 | scope | system_disclosure | `SELECT * FROM duckdb_databases WHERE EXISTS (WITH duckdb_databases AS ` |
| guard_only | c05 | scope | system_disclosure | `SELECT path FROM duckdb_databases WHERE EXISTS (WITH duckdb_databases ` |
| guard+ro | c05 | scope | system_disclosure | `SELECT path FROM duckdb_databases WHERE EXISTS (WITH duckdb_databases ` |
| guard_only | c06 | scope | system_disclosure | `SELECT c_name, (SELECT max(path) FROM duckdb_databases) AS p FROM cust` |
| guard+ro | c06 | scope | system_disclosure | `SELECT c_name, (SELECT max(path) FROM duckdb_databases) AS p FROM cust` |
| guard_only | c08 | scope | system_disclosure | `SELECT * FROM region UNION ALL SELECT database_oid, path, type FROM du` |
| guard+ro | c08 | scope | system_disclosure | `SELECT * FROM region UNION ALL SELECT database_oid, path, type FROM du` |
| guard_only | p04 | parser | session_state | `SELECT * FROM (PIVOT region ON r_name USING count(*))` |
| guard+ro | p04 | parser | session_state | `SELECT * FROM (PIVOT region ON r_name USING count(*))` |

_Environment: {'python': '3.13.17', 'duckdb': '1.5.5', 'sqlglot': '30.25.0', 'timestamp': '2026-10-26T15:39:25'}_

## Exp 1b: mutation fuzzing

2253 unique mutants from 91 seed attacks (up to 25 per seed, depth 3, rng seed 0).

| config | mutants allowed | allowed AND harmful | seed attacks | top mutators |
|---|---|---|---|---|
| guard_only | 288 | 235 | c01, c02, c03, c04, c05, c06, c08, f03, p04, x09, y02, y12 | odd_whitespace (56), wrap_subquery (52), inline_comments (51), flip_case (50) |
| guard+ro | 288 | 153 | c04, c05, c06, c08, p04, x09, y02, y12 | odd_whitespace (41), wrap_subquery (35), flip_case (32), wrap_cte (29) |
| hardened+ro | 25 | 0 | - | - |
| strict+ro | 0 | 0 | - | - |

_Environment: {'python': '3.13.17', 'duckdb': '1.5.5', 'sqlglot': '30.25.0', 'timestamp': '2026-10-26T15:43:29'}_

## Exp 2: over-blocking of legitimate queries

Cells: queries served with the same rows as an unprotected connection / queries.

| set | none | ro_only | guard_only | guard+ro | hardened+ro | strict+ro |
|---|---|---|---|---|---|---|
| gold_core | 40/40 | 40/40 | 40/40 | 40/40 | 40/40 | 40/40 |
| gold_glossary | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 |
| tricky:duckdb | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| tricky:function | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 |
| tricky:generator | 2/2 | 2/2 | 0/2 | 0/2 | 0/2 | 0/2 |
| tricky:keyword | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| tricky:structure | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| **all** | **92/92** | **92/92** | **90/92** | **90/92** | **90/92** | **90/92** |

Legitimate queries not served in a guarded configuration:

| config | id | verdict | reason |
|---|---|---|---|
| guard_only | b33 | block | table functions are not allowed: RANGE(CAST('1995-01-01' AS DATE), CAST('1996-01 |
| guard+ro | b33 | block | table functions are not allowed: RANGE(CAST('1995-01-01' AS DATE), CAST('1996-01 |
| hardened+ro | b33 | block | table functions are not allowed: RANGE(CAST('1995-01-01' AS DATE), CAST('1996-01 |
| strict+ro | b33 | block | table functions are not allowed: RANGE(CAST('1995-01-01' AS DATE), CAST('1996-01 |
| guard_only | b34 | block | table functions are not allowed: GENERATE_SERIES(CAST('1995-01-01' AS DATE), CAS |
| guard+ro | b34 | block | table functions are not allowed: GENERATE_SERIES(CAST('1995-01-01' AS DATE), CAS |
| hardened+ro | b34 | block | table functions are not allowed: GENERATE_SERIES(CAST('1995-01-01' AS DATE), CAS |
| strict+ro | b34 | block | table functions are not allowed: GENERATE_SERIES(CAST('1995-01-01' AS DATE), CAS |

Oracle false alarms on legitimate queries: 0.

_Environment: {'python': '3.13.17', 'duckdb': '1.5.5', 'sqlglot': '30.25.0', 'timestamp': '2026-10-26T15:43:41'}_
