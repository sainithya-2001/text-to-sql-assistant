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
