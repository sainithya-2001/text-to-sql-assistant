# Eval: core_baseline

### Core set

| Config | Easy | Medium | Hard | **Overall** | Retried | Retrieval recall | Cost |
|---|---|---|---|---|---|---|---|
| `claude-haiku-5-5/full` | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 0 | n/a | $0.004 |
| `claude-haiku-5-5/retrieved` | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 1 | 98% (39/40) | $0.011 |
| `claude-sonnet-5-5/full` | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 0 | n/a | $0.083 |
| `claude-sonnet-5-5/retrieved` | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 1 | 98% (39/40) | $0.220 |

Total spend: **$0.318** (cap $0.40).

## Failures

| Config | Question | Outcome |
|---|---|---|
| `claude-haiku-5-5/retrieved` | h05 | declined: The schema has no orders table (so order dates for 1994 are unavailable) and no  |
| `claude-sonnet-5-5/retrieved` | h05 | declined: The schema has no orders table (order dates and the order-to-customer link are m |
