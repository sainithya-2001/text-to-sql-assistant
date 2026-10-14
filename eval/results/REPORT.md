### Core set: 40 questions, metrics spelled out in the question

| Model | Schema | Glossary | Easy | Medium | Hard | **Accuracy** | Retries | $ / question | Avg latency |
|---|---|---|---|---|---|---|---|---|---|
| Haiku 5.5 | full | off | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 0 | $0.0001 | 1.1s |
| Haiku 5.5 | retrieved | off | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 1 | $0.0003 | 1.2s |
| Haiku 5.5 | retrieved | on | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 0 | $0.0003 | 1.2s |
| Sonnet 5.5 | full | off | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 0 | $0.0021 | 1.6s |
| Sonnet 5.5 | retrieved | off | 100% (14/14) | 100% (14/14) | 92% (11/12) | **98% (39/40)** | 1 | $0.0055 | 1.6s |
| Sonnet 5.5 | retrieved | on | 100% (14/14) | 100% (14/14) | 100% (12/12) | **100% (40/40)** | 1 | $0.0059 | 1.7s |

### Glossary set: 12 questions using undefined business terms

| Model | Schema | Glossary | **Accuracy** | Retries | $ / question | Avg latency |
|---|---|---|---|---|---|---|
| Haiku 5.5 | full | off | **58% (7/12)** | 0 | $0.0002 | 1.6s |
| Haiku 5.5 | full | on | **100% (12/12)** | 0 | $0.0002 | 1.4s |
| Haiku 5.5 | retrieved | off | **42% (5/12)** | 0 | $0.0003 | 1.6s |
| Haiku 5.5 | retrieved | on | **100% (12/12)** | 0 | $0.0003 | 1.6s |
| Sonnet 5.5 | full | off | **75% (9/12)** | 3 | $0.0035 | 2.1s |
| Sonnet 5.5 | full | on | **100% (12/12)** | 0 | $0.0030 | 1.8s |
| Sonnet 5.5 | retrieved | on | **100% (12/12)** | 0 | $0.0063 | 1.6s |

### Ambiguity set: 5 should get a clarifying question, 3 have a cue and should be answered

| Model | Schema | Glossary | **Accuracy** | Retries | $ / question | Avg latency |
|---|---|---|---|---|---|---|
| Haiku 5.5 | full | off | **25% (2/8)** | 0 | $0.0002 | 2.0s |
| Haiku 5.5 | full | on | **100% (8/8)** | 0 | $0.0000 | 0.6s |
| Haiku 5.5 | retrieved | off | **25% (2/8)** | 0 | $0.0004 | 2.0s |
| Haiku 5.5 | retrieved | on | **100% (8/8)** | 0 | $0.0001 | 0.6s |
| Sonnet 5.5 | full | off | **25% (2/8)** | 2 | $0.0034 | 2.2s |
| Sonnet 5.5 | full | on | **100% (8/8)** | 0 | $0.0009 | 0.7s |
| Sonnet 5.5 | retrieved | on | **100% (8/8)** | 0 | $0.0026 | 0.7s |

Spend for these runs: **$0.792** (each run had its own hard cap).
