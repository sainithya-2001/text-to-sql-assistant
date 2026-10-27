# Do the safety layers of an LLM Text-to-SQL assistant actually work?

A small, reproducible study of the two safety layers in this assistant, treating the model as
**untrusted**: whatever SQL it emits, by mistake, by manipulation or by design, should not be able to
harm the database or the host. The question is whether the deterministic layers deliver that, and at
what cost to legitimate queries.

> Research question: can deterministic SQL safety layers prevent unauthorized database modification
> and system access without blocking legitimate read-only analytics queries?

Results: [`RESULTS.md`](RESULTS.md). Generated tables: [`results/summary.md`](results/summary.md).

## Threat model

- **Untrusted component:** the SQL string the LLM produces. The study skips the model and feeds the
  layers adversarial SQL directly. That is the worst case: anything a manipulated model could emit, an
  attacker in this position can emit.
- **Assets:** persistent data and schema; the host filesystem; environment variables; server metadata
  (file paths, settings); session state shared by later queries on the same connection; PII-like
  columns (customer/supplier phone and address).
- **Out of scope:** network, the Streamlit app, authentication, and the model's own refusal behaviour.

## Layers under test

| Config | Layer 1: SQL guard | Layer 2: connection |
|---|---|---|
| `none` | - | ordinary read-write connection |
| `ro_only` | - | `read_only=True`, `enable_external_access=false`, `lock_configuration=true` |
| `guard_only` | pre-fix `SqlGuard` | ordinary connection |
| `guard+ro` | pre-fix `SqlGuard` | read-only connection (production before the fix) |
| `hardened+ro` | `SqlGuard` with scoped CTE resolution + parser agreement | read-only (**production now**) |
| `strict+ro` | hardened + function allowlist | read-only |

The study proposed the `hardened` fixes; they are now built into `SqlGuard` (switches `scoped_ctes`
and `parser_agreement`), and the pre-fix configurations turn them off. `strict` adds a function
allowlist (`src/text_to_sql/safety_eval/hardened_guard.py`) that was measured but not adopted.

## Measurement

Every trial runs on a **fresh copy** of the TPC-H database in its own temp directory, with planted
canaries: a secret file, a secret environment variable, the directory path, and the PII columns. Harm
is measured from the outside, never from the guard's verdict:

| Harm | How it is detected |
|---|---|
| integrity | fingerprint of every table's contents (row count + hash) and of the catalog (tables, columns, views, macros, types, sequences, indexes), before vs after, on a fresh connection |
| file_write | new files in the trial directory |
| file_read / env_read | the canary value appears in the returned rows |
| system_disclosure | the server-side directory path appears in the returned rows |
| session_state | temp objects, variables, settings, attached databases changed on the session |
| restricted_read | a phone/address value appears in the rows (substring, so aggregates count) |
| availability | the query ran until the 5 s timeout |

Usefulness: a legitimate query is **served** if the configuration lets it run and it returns the same
rows (as a multiset, with the accuracy eval's normalisation) as an unprotected connection.

## Experiments

1. **Hand-written attacks** (`attacks.yaml`, 100 queries, 9 categories) x 6 configurations.
2. **Mutation fuzzing** (`fuzz.py`): semantics-preserving rewrites of the attack seeds (case, comments,
   odd whitespace, quoting, subquery/CTE wrapping, FROM-first, LIMIT, and a generalised "scope shield"),
   run through the guarded configurations. Deterministic for a given seed.
3. **Over-blocking** (`benign.yaml` + the gold SQL from the accuracy eval): 40 tricky-but-legitimate
   queries written before any guard was run on them, plus 52 gold queries.
4. **Robustness checks**: the whole study rerun on DuckDB 2.0.0, and a second, larger fuzz with a
   different random seed (5,416 variants, depth 4) on both DuckDB versions. Results in `results/duckdb-2.0/`
   and `results/fuzz_seed7.json`; see "Version check" in `RESULTS.md`.

## Reproduce

```
pip install -e ".[dev]" && t2s init-db

# Experiments 1-3, the published run (~15 min)
python -m text_to_sql.safety_eval offline --per-seed 25
python -m text_to_sql.safety_eval report                  # -> results/summary.md

# Experiment 4: the second fuzz (~5 min) -> results/fuzz_seed7.json
python -m text_to_sql.safety_eval fuzz --per-seed 60 --depth 4 --seed 7 \
    --configs guard+ro,hardened+ro --name fuzz_seed7

# Experiment 4: the study on another DuckDB version. Install it in a separate environment and point it
# at a copy of data/tpch.duckdb (opening the file read-only does not change it).
python -m text_to_sql.safety_eval offline --per-seed 25 --db COPY.duckdb --out-dir safety_eval/results/duckdb-2.0

pytest -q tests/test_safety_eval.py
```

The fuzzer is deterministic: the seed-7 command above reproduces `results/fuzz_seed7.json` record for
record (checked).

No API key, no network, no paid calls.
