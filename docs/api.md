# JSON API

Default base: `http://127.0.0.1:8081`. Failures return an `error` string. Validation errors use HTTP 400; configured model failures use 503. Initial indexing selects a repository through the CLI; source code is never executed.

| Method | Path | Input / response |
|---|---|---|
| GET | `/api/health` | Process health: `{ "status": "ok" }` |
| GET | `/api/status` | Counts, warnings, model configuration, modes, refresh availability |
| POST | `/api/search` | `{ "question": "verify token", "k": 5 }`; symbols/source windows |
| POST | `/api/ask` | Same input; evidence or generated claims with source/line citations |
| POST | `/api/impact` | `{ "symbol": "auth.verify_token", "depth": 3 }`; target and reachable callers |
| POST | `/api/reindex` | `{}`; refresh saved repository, report changed/unchanged/deleted counts |

```bash
curl http://127.0.0.1:8081/api/ask -H 'Content-Type: application/json' -d '{"question":"What does verify_token return?","k":3}'
curl http://127.0.0.1:8081/api/reindex -H 'Content-Type: application/json' -d '{}'
```

Questions allow 1–2,000 nonblank characters. `k` is an integer from 1 to 20; `depth` from 1 to 10. Use an exact record ID from search when names are ambiguous. Line numbers are 1-based and refer to the indexed snapshot. Refresh after source edits; no server restart is needed. Reindexing uses the saved CLI-selected root and accepts no new root from the API.

`latency_ms` measures retrieval; `total_ms` on answers includes generation. Evidence mode returns source excerpts without invented claims. Ollama mode returns claims with citation ID, exact attached quote, path, start and end lines. Citations establish provenance, not correctness. Generation uses at most 12,000 source characters, at most 6,000 per source, in retrieval order; full retrieved evidence is also returned.

`/api/status` is a lightweight check; `ollama_ready: null` means it has not probed the model endpoint. `python -m codeatlas doctor` loads the embedding model and checks Ollama, returning a nonzero exit status on incomplete setup. Keep the unauthenticated server local.
