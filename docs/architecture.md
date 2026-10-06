# Architecture and decisions

The scanner prefers `git ls-files --cached --others --exclude-standard`. If unavailable or unsuccessful, it walks the directory while pruning hidden/generated folders; this fallback does not interpret .gitignore. It skips symlinks, sensitive-looking names, unsupported extensions and files over 512 KiB, and caps supported files at 10,000. Exclusions do not replace secret scanning or access control.

Python is parsed with `ast.parse`, never imported. Records retain nested qualified names, decorators, docstrings, line ranges and text. Every file has 80-line text windows with 16-line overlap, including Python module-level code after line 120. Python functions/classes also get symbol records; these overlap module windows. Syntax-error files fall back to text windows with warnings. Long symbol inputs can be truncated by an embedding model's token limit.

Scope-local binding collection recognizes parameters, assignments, globals/nonlocals, imports and aliases without leaking nested imports into siblings. Function scopes do not close over class namespaces. Conventional `self`/`cls` calls are linked only when their receiver is not reassigned; static methods do not get an instance receiver. Package reexports and common src layouts are supported. Repeated definitions get distinct record IDs; ambiguous targets stay unresolved. No global short-name guessing is used.

The graph is conservative, not a full Python runtime model. Dynamic object dispatch, inheritance, lambdas/comprehensions, control-flow-dependent rebinding and external callers remain incomplete. Unresolved calls are retained in CLI status metadata. Reverse-call breadth-first traversal uses depth limits and a visited set for cycles.

A versioned file cache reuses parsing results for unchanged content hashes. Changes and deletions recompute the graph and replace all records, edges, metadata and file-cache entries in one transaction. Every build assigns a revision. The server detects a changed revision on its next operation and reads one consistent SQLite snapshot; no restart is required. Changes to source require explicit reindexing.

BM25 uses inverted token postings. Optional normalized dense vectors are cached in `<db>.vectors.sqlite3` by model name and content hash, then scanned in memory and fused with BM25 using reciprocal ranks. Query vectors are computed per request. The disposable cache uses JSON numeric arrays; it retains unused vectors after deletion, not source text. Remove it when replacing model weights under the same name/path.

Ollama generates at most four JSON claims from bounded source context, citing short IDs. The server attaches exact source excerpts and their file/line ranges. Invalid output gets one retry; persistent failures are visible. Citation provenance does not guarantee a correct explanation. Without a model, ask returns source evidence explicitly labeled as such.

The local web server checks Host/Origin, bounds input and renders source as text. The Docker image runs as a non-root user and supports read-only source mounts and persistent index volumes. Hosted authentication, tenancy and remote access controls are outside this scope.

Primary references: [Python AST](https://docs.python.org/3/library/ast.html), [Git ls-files](https://git-scm.com/docs/git-ls-files), [Sentence Transformers](https://sbert.net/docs/package_reference/sentence_transformer/model.html), [Ollama generation](https://docs.ollama.com/api/generate).
