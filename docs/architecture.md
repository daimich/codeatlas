# Architecture and engineering decisions

The scanner uses `git ls-files --cached --others --exclude-standard` when Git is available. Otherwise it walks the directory while pruning generated and hidden folders. It skips symlinks, sensitive-looking filenames, unsupported extensions, and files over 512 KiB; at most 10,000 supported files are accepted. These exclusions do not replace secret scanning or access control.

Python files are parsed with `ast.parse`, never imported. Records retain qualified names, docstrings, decorator-aware start lines, end lines, and source text. Module records retain the first 120 lines; non-Python files and syntax-error fallbacks use 80-line windows with 16 lines of overlap. Class and function records can overlap. Dense encoders may truncate long symbol text to their model token limit; BM25 scores the full stored record.

The resolver links lexical names, imported names and aliases, relative imports, and `self`/`cls` method names when the qualified target exists in the snapshot. It does not resolve arbitrary objects or fall back to global short-name guessing. Python scoping and runtime dispatch are richer than this resolver: shadowing, local import scope, inheritance, closures, and dynamic bindings can still create incorrect or missing edges. Every unresolved call is retained in metadata.

The complete snapshot is replaced in one SQLite transaction. Reindexing removes old symbols and edges, including deleted files. Hash metadata is saved for a future incremental implementation; the current indexer reparses all files. A running service keeps an immutable in-memory snapshot and must restart to see new index data.

Impact analysis walks the reverse call graph with breadth-first search. A visited set prevents cycles from duplicating symbols, and the depth limit bounds traversal. Results represent possible static callers, not a promise that a change will affect them at runtime.

Retrieval uses BM25 with camel-case and underscore splitting. Optional normalized Sentence Transformers vectors contribute a dense ranking; reciprocal rank fusion combines those rankings. A general text model is a baseline, not a code-comprehension benchmark. There is no LLM-generated code explanation in the current release.

## Challenges this implementation addresses

- Avoiding execution of potentially untrusted repository code.
- Resolving imports and preserving source ranges through AST indexing.
- Safely handling incomplete or syntactically invalid repositories.
- Preventing stale symbols after files are renamed or deleted.
- Tracing transitive callers with cycles and ambiguous short names.

## Primary implementation references

- [Python AST documentation](https://docs.python.org/3/library/ast.html)
- [Git ls-files](https://git-scm.com/docs/git-ls-files)
- [Sentence Transformers encode API](https://sbert.net/docs/package_reference/sentence_transformer/model.html)

## Scaling path

Add incremental file hashing, Tree-sitter symbol extraction for TypeScript/Go/Rust, lexical binding analysis and graph resolution tests, a vector index, evaluated code-specialized embeddings, and commit-aware symbol provenance. Build an explanation layer only after retrieval and source citation quality are measured.
