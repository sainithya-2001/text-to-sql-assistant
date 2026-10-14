# Eval: glossary_sets

> Resumed twice after a crash (sqlglot TokenError, fixed). Two crashed Sonnet calls (~$0.004) ran before results were saved and are not included in spent_usd.

### Ambiguity set

| Config | Easy | Medium | Hard | **Overall** | Retried | Retrieval recall | Cost |
|---|---|---|---|---|---|---|---|
| `claude-haiku-5-5/full` | - | 17% (1/6) | 50% (1/2) | **25% (2/8)** | 0 | n/a | $0.002 |
| `claude-haiku-5-5/full+glossary` | - | 100% (6/6) | 100% (2/2) | **100% (8/8)** | 0 | n/a | $0.000 |
| `claude-haiku-5-5/retrieved` | - | 17% (1/6) | 50% (1/2) | **25% (2/8)** | 0 | 100% (3/3) | $0.003 |
| `claude-haiku-5-5/retrieved+glossary` | - | 100% (6/6) | 100% (2/2) | **100% (8/8)** | 0 | 100% (3/3) | $0.001 |
| `claude-sonnet-5-5/full` | - | 17% (1/6) | 50% (1/2) | **25% (2/8)** | 2 | n/a | $0.027 |
| `claude-sonnet-5-5/full+glossary` | - | 100% (6/6) | 100% (2/2) | **100% (8/8)** | 0 | n/a | $0.007 |
| `claude-sonnet-5-5/retrieved+glossary` | - | 100% (6/6) | 100% (2/2) | **100% (8/8)** | 0 | 100% (3/3) | $0.021 |

### Glossary set

| Config | Easy | Medium | Hard | **Overall** | Retried | Retrieval recall | Cost |
|---|---|---|---|---|---|---|---|
| `claude-haiku-5-5/full` | 100% (1/1) | 43% (3/7) | 75% (3/4) | **58% (7/12)** | 0 | n/a | $0.002 |
| `claude-haiku-5-5/full+glossary` | 100% (1/1) | 100% (7/7) | 100% (4/4) | **100% (12/12)** | 0 | n/a | $0.002 |
| `claude-haiku-5-5/retrieved` | 100% (1/1) | 43% (3/7) | 25% (1/4) | **42% (5/12)** | 0 | 83% (10/12) | $0.004 |
| `claude-haiku-5-5/retrieved+glossary` | 100% (1/1) | 100% (7/7) | 100% (4/4) | **100% (12/12)** | 0 | 100% (12/12) | $0.004 |
| `claude-sonnet-5-5/full` | 100% (1/1) | 71% (5/7) | 75% (3/4) | **75% (9/12)** | 3 | n/a | $0.042 |
| `claude-sonnet-5-5/full+glossary` | 100% (1/1) | 100% (7/7) | 100% (4/4) | **100% (12/12)** | 0 | n/a | $0.036 |
| `claude-sonnet-5-5/retrieved+glossary` | 100% (1/1) | 100% (7/7) | 100% (4/4) | **100% (12/12)** | 0 | 100% (12/12) | $0.075 |

Total spend: **$0.226** (cap $0.24).

## Failures

| Config | Question | Outcome |
|---|---|---|
| `claude-haiku-5-5/full` | g02 | ran, wrong result |
| `claude-haiku-5-5/full` | g03 | ran, wrong result |
| `claude-haiku-5-5/full` | g05 | ran, wrong result |
| `claude-haiku-5-5/full` | g07 | ran, wrong result |
| `claude-haiku-5-5/full` | g10 | ran, wrong result |
| `claude-haiku-5-5/full` | a01 | answered instead of asking for clarification |
| `claude-haiku-5-5/full` | a02 | answered instead of asking for clarification |
| `claude-haiku-5-5/full` | a03 | answered instead of asking for clarification |
| `claude-haiku-5-5/full` | a04 | answered instead of asking for clarification |
| `claude-haiku-5-5/full` | a05 | answered instead of asking for clarification |
| `claude-haiku-5-5/full` | a08 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | g01 | wrong result; retrieval missed lineitem |
| `claude-haiku-5-5/retrieved` | g02 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | g03 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | g04 | declined: The schema has no cost data (such as part supply cost or purchase price), so pro |
| `claude-haiku-5-5/retrieved` | g05 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | g07 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | g10 | ran, wrong result |
| `claude-haiku-5-5/retrieved` | a01 | answered instead of asking for clarification |
| `claude-haiku-5-5/retrieved` | a02 | answered instead of asking for clarification |
| `claude-haiku-5-5/retrieved` | a03 | answered instead of asking for clarification |
| `claude-haiku-5-5/retrieved` | a04 | answered instead of asking for clarification |
| `claude-haiku-5-5/retrieved` | a05 | answered instead of asking for clarification |
| `claude-haiku-5-5/retrieved` | a08 | ran, wrong result |
| `claude-sonnet-5-5/full` | g03 | ran, wrong result |
| `claude-sonnet-5-5/full` | g05 | ran, wrong result |
| `claude-sonnet-5-5/full` | g10 | ran, wrong result |
| `claude-sonnet-5-5/full` | a01 | answered instead of asking for clarification |
| `claude-sonnet-5-5/full` | a02 | answered instead of asking for clarification |
| `claude-sonnet-5-5/full` | a03 | answered instead of asking for clarification |
| `claude-sonnet-5-5/full` | a04 | answered instead of asking for clarification |
| `claude-sonnet-5-5/full` | a05 | answered instead of asking for clarification |
| `claude-sonnet-5-5/full` | a08 | ran, wrong result |
