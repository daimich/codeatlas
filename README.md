# CodeAtlas

**Find the code. Follow the connections.**

CodeAtlas searches local repositories with file/line references, traces Python callers, and optionally generates source-cited explanations using Ollama. Version 0.2 adds incremental indexing, live refresh, persistent embeddings, stronger lexical call resolution, and browser, Docker, and real-model acceptance tests.

The supported scope is a single-user local application. Static caller analysis is approximate; generated explanations require inspection of their source excerpts.

## Start locally

Requires Python 3.11+. The default source checkout has no third-party dependencies:

```bash
git clone https://github.com/daimich/codeatlas.git
cd codeatlas
python -m codeatlas index examples/sample_repo
python -m codeatlas doctor
python -m codeatlas serve
```

For a downloaded archive, extract it and start from its project folder. Open **http://127.0.0.1:8081**, search for “Validate bearer token,” then select **Trace callers** on a function result. Choose **Explain with sources** for an explanation when a model is configured, or inspect source excerpts in evidence mode.

```bash
python -m codeatlas search "Authenticate request Authorization header"
python -m codeatlas ask "What does verify_token return?"
python -m codeatlas impact auth.verify_token --depth 3
```

Install with `python -m pip install .` to use the equivalent `codeatlas` command. On Windows, `py` may replace `python`.

## Index your repository

```bash
python -m codeatlas index /path/to/repository
python -m codeatlas serve
```

After editing source, select **Refresh index** in the browser or run `python -m codeatlas reindex`. Only changed files are reparsed; unchanged parsed records are reused, deleted files are removed, and the graph is recomputed. A running server picks up CLI index changes on its next query. There is no filesystem watcher; refresh explicitly after edits.

Data lives in `.codeatlas/index.sqlite3`. Use the global `--db /path/to/index.sqlite3` option for separate workspaces. The API refreshes only the repository selected through the CLI; it cannot select an arbitrary server-side directory.

| Capability | Behavior |
|---|---|
| Python structure | AST functions/classes, nested names, decorators, docstrings, source ranges |
| Text search | Complete file windows for Python, JS/TS, Go, Rust, Java, C/C++, and Markdown |
| Retrieval | BM25 inverted index; optional dense embeddings combined by reciprocal rank fusion |
| Explanations | Optional Ollama claims with server-attached excerpts and line references |
| Caller graph | Lexical scopes, imports/aliases, package reexports, common `src` layouts, `self`/`cls` calls |
| Ambiguity | Repeated definitions do not crash indexing; ambiguous or shadowed targets remain unresolved |
| Impact | Reverse-call breadth-first traversal, depth limits, cycle detection |
| Persistence | Atomic SQLite snapshots, incremental parsing, persistent vectors, live refresh |

Source is parsed as data, never imported or executed. Git-tracked/unignored files are preferred; generated directories, symlinks, sensitive-looking filenames, unsupported files, and files over 512 KiB are skipped. These exclusions are not a secret scanner. The scan accepts at most 10,000 supported files.

## Enable AI

Create/activate a virtual environment if desired, then install semantic support. Install and start [Ollama](https://ollama.com/download) separately (`ollama serve` if needed):

```bash
python -m pip install '.[semantic]'
ollama pull qwen2.5:3b
python -m codeatlas --semantic-model sentence-transformers/all-MiniLM-L6-v2 --ollama-model qwen2.5:3b doctor
python -m codeatlas --semantic-model sentence-transformers/all-MiniLM-L6-v2 --ollama-model qwen2.5:3b serve
```

Both models are optional and independent. Embedding weights download on first use; a local model directory also works. `doctor` loads the embedding model and checks Ollama's installed models, returning a failure exit status for incomplete setup. The embedding model is a general-text baseline, not a code-specialized model. Evaluate it on your repository before making quality claims.

`SEMANTIC_MODEL`, `OLLAMA_MODEL`, and `OLLAMA_URL` environment variables provide the same defaults as the CLI options. The default endpoint is `http://localhost:11434`. Source excerpts are sent to the configured endpoint; the default stays on your machine.

The generator uses bounded source context and structured JSON. The server validates citation IDs and attaches exact stored excerpts and line locations. Unavailable models and invalid output fail visibly. These checks establish provenance, not the correctness of the explanation.

## Docker

```bash
docker compose up --build -d
```

Open **http://127.0.0.1:8081**. The sample repository is preindexed. Named volumes retain the index and caches across container replacement. `docker compose down` keeps data; `docker compose down -v` deletes it.

To index your own source with plain Docker, keep the same read-only source mount when serving so refresh remains available:

```bash
docker build -t codeatlas .
docker run --rm -v codeatlas-data:/data -v /absolute/path/repo:/repo:ro codeatlas index /repo
docker run --rm -p 127.0.0.1:8081:8081 -v codeatlas-data:/data -v /absolute/path/repo:/repo:ro codeatlas
```

For the Compose AI profile, create a local `.env` file:

```dotenv
ENABLE_SEMANTIC=1
SEMANTIC_MODEL=sentence-transformers/all-MiniLM-L6-v2
OLLAMA_MODEL=qwen2.5:3b
```

```bash
docker compose --profile ai up --build -d
docker compose exec ollama ollama pull qwen2.5:3b
docker compose exec codeatlas doctor
```

Only Compose automatically reads `.env`. The AI image downloads CPU dependencies and model weights. Default Docker startup, source mounting, refresh and persistence are tested in CI; the optional Compose AI profile combines the same adapters tested by the separate real-model workflow.

## Verification and limits

```bash
python -m unittest discover -s tests -v
python -m codeatlas index examples/sample_repo
python -m codeatlas eval
```

`eval` measures Recall@5 and MRR@5 on six toy symbol queries. These fixtures do not establish general code-comprehension accuracy. See [validation](docs/validation.md), [API](docs/api.md), [architecture](docs/architecture.md), and [remaining extensions](docs/roadmap.md).

The caller graph omits arbitrary object dispatch, inheritance, external callers, lambdas/comprehensions, and runtime metaprogramming. It can miss dependencies; confirm results in source. Non-Python languages have text search only. The local HTTP server has no accounts, tenant isolation, or TLS. Dense search scans vectors in memory; large-scale indexing and hosted team deployment are outside this release.

MIT licensed. The fixture repository is fictional demonstration code.
