"""Parse source as data; build conservative, statically resolved call edges."""

import ast
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from contextlib import closing

EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".md"}
SKIP = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", ".codeatlas", "__pycache__"}
MAX_FILE = 512 * 1024
MAX_FILES = 10000


def source_files(root):
    """Use Git's tracked/unignored files when available; prune common build dirs otherwise."""
    root = root.resolve()
    git_paths = None
    try:
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                cwd=root, capture_output=True, timeout=10, check=True)
        git_paths = [Path(p) for p in os.fsdecode(result.stdout).split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        pass
    if git_paths is None:
        candidates = []
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            candidates.extend(Path(directory, name).relative_to(root) for name in files)
            if len(candidates) > MAX_FILES * 5:
                raise ValueError("Repository exceeds scan limit")
    else:
        candidates = git_paths
    selected = []
    for relative in sorted(set(candidates)):
        if relative.is_absolute() or ".." in relative.parts or any(p in SKIP or p.startswith(".") for p in relative.parts):
            continue
        path = root / relative
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
            continue
        if path.suffix.lower() not in EXTENSIONS or not path.is_file() or path.stat().st_size > MAX_FILE:
            continue
        if any(word in path.name.lower() for word in ("secret", "credential", "private_key")):
            continue
        selected.append(path)
        if len(selected) > MAX_FILES:
            raise ValueError("Repository exceeds 10,000 source files")
    return selected


def module_name(path):
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Parser(ast.NodeVisitor):
    def __init__(self, relative, text):
        self.path = relative.as_posix()
        self.module = module_name(relative)
        self.lines = text.splitlines()
        self.scope = []
        self.active_function = None
        self.symbols = []
        self.calls = []
        self.imports = {}

    def visit_Import(self, node):
        for alias in node.names:
            self.imports[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]

    def visit_ImportFrom(self, node):
        base = node.module or ""
        if node.level:
            package = self.module if self.path.endswith("/__init__.py") else self.module.rpartition(".")[0]
            parts = package.split(".") if package else []
            base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
        for alias in node.names:
            if alias.name != "*":
                self.imports[alias.asname or alias.name] = ".".join(filter(None, (base, alias.name)))

    def add_symbol(self, node, kind):
        qualified = ".".join([self.module, *self.scope, node.name])
        identifier = f"{self.path}:{qualified}"
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        text = "\n".join(self.lines[start - 1:node.end_lineno])
        self.symbols.append({"id": identifier, "path": self.path, "name": node.name, "qualified": qualified,
                             "kind": kind, "start": start, "end": node.end_lineno,
                             "text": text, "search_text": f"{self.path} {qualified} {ast.get_docstring(node) or ''}\n{text}"})
        return identifier

    def visit_ClassDef(self, node):
        self.add_symbol(node, "class")
        self.scope.append(node.name)
        previous = self.active_function
        self.active_function = None
        for child in node.body:
            self.visit(child)
        self.active_function = previous
        self.scope.pop()

    def visit_FunctionDef(self, node):
        identifier = self.add_symbol(node, "function")
        previous = self.active_function
        self.active_function = identifier
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()
        self.active_function = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if self.active_function:
            target = ast.unparse(node.func)
            self.calls.append({"source": self.active_function, "target": target, "line": node.lineno})
        self.generic_visit(node)


def parse_file(relative, text):
    if relative.suffix == ".py":
        try:
            tree = ast.parse(text)
            parser = Parser(relative, text)
            parser.visit(tree)
            # Include imports, constants, and module-level statements in one searchable record.
            module_text = "\n".join(text.splitlines()[:120])
            record = {"id": f"{relative.as_posix()}:module", "path": relative.as_posix(), "name": relative.stem,
                      "qualified": module_name(relative), "kind": "module", "start": 1,
                      "end": min(120, len(text.splitlines())), "text": module_text,
                      "search_text": f"{relative.as_posix()}\n{module_text}"}
            return [record, *parser.symbols], parser.calls, parser.imports, None
        except SyntaxError as exc:
            error = f"{relative}:{exc.lineno}: {exc.msg}"
    else:
        error = None
    records = []
    lines = text.splitlines()
    for start in range(0, len(lines), 64):
        excerpt = "\n".join(lines[start:start + 80])
        records.append({"id": f"{relative.as_posix()}:{start + 1}", "path": relative.as_posix(),
                        "name": relative.stem, "qualified": relative.as_posix(), "kind": "text",
                        "start": start + 1, "end": min(start + 80, len(lines)), "text": excerpt,
                        "search_text": f"{relative.as_posix()}\n{excerpt}"})
        if start + 80 >= len(lines):
            break
    return records, [], {}, error


def resolve_calls(records, pending, imports):
    """Resolve only lexical names, imported names, and self/cls methods; no global name guessing."""
    qualified = {r["qualified"]: r["id"] for r in records if r["kind"] in {"function", "class"}}
    by_id = {r["id"]: r for r in records}
    edges, unresolved = [], []
    for call in pending:
        source = by_id[call["source"]]
        target = call["target"]
        first, _, tail = target.partition(".")
        candidates = []
        aliases = imports.get(source["path"], {})
        if first in aliases:
            candidates.append(aliases[first] + ("." + tail if tail else ""))
        elif first in {"self", "cls"} and tail:
            candidates.append(source["qualified"].rpartition(".")[0] + "." + tail)
        elif target.isidentifier():
            parts = source["qualified"].split(".")
            # Start at the nested function's own scope then walk outward.
            candidates.extend(".".join([*parts[:i], target]) for i in range(len(parts), 0, -1))
        found = next((qualified[name] for name in candidates if name in qualified), None)
        if found:
            edges.append({"source": call["source"], "target": found, "line": call["line"]})
        else:
            unresolved.append(call)
    return edges, unresolved


class Index:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS edges (source TEXT, target TEXT, line INTEGER);
                CREATE INDEX IF NOT EXISTS edges_target ON edges(target);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def build(self, root):
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError("Repository directory does not exist")
        records, calls, imports, warnings = [], [], {}, []
        files = source_files(root)
        digests = {}
        for path in files:
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8")
            except (UnicodeDecodeError, OSError):
                warnings.append(f"Skipped unreadable/non-UTF-8 file: {path.relative_to(root)}")
                continue
            relative = path.relative_to(root)
            parsed, pending, aliases, error = parse_file(relative, text)
            records.extend(parsed)
            calls.extend(pending)
            imports[relative.as_posix()] = aliases
            digests[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
            if error:
                warnings.append(error)
        edges, unresolved = resolve_calls(records, calls, imports)
        metadata = {"root": str(root), "files": len(digests), "records": len(records), "edges": len(edges),
                    "warnings": warnings, "unresolved_calls": unresolved, "digests": digests}
        # One transaction replaces the snapshot; deletions cannot leave stale symbols or edges.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM records")
            db.execute("DELETE FROM edges")
            db.execute("DELETE FROM metadata")
            db.executemany("INSERT INTO records VALUES(?,?)", [(r["id"], json.dumps(r)) for r in records])
            db.executemany("INSERT INTO edges VALUES(?,?,?)", [(r["source"], r["target"], r["line"]) for r in edges])
            db.execute("INSERT INTO metadata VALUES('snapshot',?)", (json.dumps(metadata),))
        return metadata

    def records(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM records ORDER BY id")]

    def metadata(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
            return json.loads(row[0]) if row else {"files": 0, "records": 0, "edges": 0, "warnings": []}

    def graph(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return [{"source": row[0], "target": row[1], "line": row[2]} for row in db.execute("SELECT * FROM edges ORDER BY source,target,line")]
