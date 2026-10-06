# JSON API

The default base URL is `http://127.0.0.1:8081`. Indexing is a CLI operation; the web API cannot read arbitrary server-side paths or execute repository code.

| Method | Path | Body / response |
|---|---|---|
| GET | `/api/health` | `{ "status": "ok" }` |
| GET | `/api/status` | File, record, edge counts and indexing warnings |
| POST | `/api/search` | `{ "question": "verify token", "k": 5 }`; hits include IDs, paths, lines, and excerpts |
| POST | `/api/impact` | `{ "symbol": "auth.verify_token", "depth": 3 }`; target and reachable callers |

```bash
curl http://127.0.0.1:8081/api/search \
  -H 'Content-Type: application/json' \
  -d '{"question":"Authenticate request","k":5}'

curl http://127.0.0.1:8081/api/impact \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"auth.verify_token","depth":3}'
```

Questions are limited to 2,000 characters. `k` must be an integer from 1 to 20 and `depth` from 1 to 10. Use an exact record ID returned by search when qualified or short names are ambiguous. Lines are 1-based and refer to the indexed snapshot; reindex and restart the server to reflect source edits.

Scores are retrieval diagnostics, not confidence probabilities. The server has no multi-user authentication; keep it local.
