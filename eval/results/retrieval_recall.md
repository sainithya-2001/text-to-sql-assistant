Retrieval recall: gold tables contained in the schema sent to the model.
55 questions with gold SQL; embedder=fastembed:BAAI/bge-small-en-v1.5; hybrid retrieval + FK bridging.

| Glossary tables | k=3 | k=4 | k=5 | k=6 |
|---|---|---|---|---|
| no | 93% (51/55), 3.3 tables | 95% (52/55), 4.1 tables | 96% (53/55), 5.2 tables | 100% (55/55), 6.0 tables |
| yes | 95% (52/55), 3.3 tables | 98% (54/55), 4.2 tables | 98% (54/55), 5.2 tables | 100% (55/55), 6.0 tables |

Misses:
- k=3, no glossary: h01, h05, g01, g04
- k=4, no glossary: h05, g01, g04
- k=5, no glossary: h05, g04
- k=3, with glossary: h01, h05, g04
- k=4, with glossary: h05
- k=5, with glossary: h05
