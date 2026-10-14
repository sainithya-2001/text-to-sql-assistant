# Eval: core_glossary

### Core set

| Config | Easy | Medium | Hard | **Overall** | Retried | Retrieval recall | Cost |
|---|---|---|---|---|---|---|---|
| `claude-haiku-5-5/retrieved+glossary` | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 0 | 98% (39/40) | $0.012 |
| `claude-sonnet-5-5/retrieved+glossary` | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 1 | 98% (39/40) | $0.236 |

Total spend: **$0.247** (cap $0.28).

## Failures

| Config | Question | Outcome |
|---|---|---|
| `claude-haiku-5-5/retrieved+glossary` | h05 | declined: The schema has no region table, so "ASIA" cannot be mapped to a region key; nati |
