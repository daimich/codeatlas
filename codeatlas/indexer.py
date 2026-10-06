"""Parse source as data; build conservative, statically resolved call edges."""

import hashlib
import json
import os
import sqlite3
import subprocess
import uuid
from pathlib import Path
from contextlib import closing
from .parser import parse_file, resolve_calls

EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".md"}
SKIP = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", ".codeatlas", "__pycache__"}
MAX_FILE = 512 * 1024
MAX_FILES = 10000
PARSER_VERSION = 2


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
                CREATE TABLE IF NOT EXISTS file_cache (path TEXT PRIMARY KEY, digest TEXT, payload TEXT);
            """)

    def build(self, root):
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError("Repository directory does not exist")
        previous = self.metadata()
        with closing(sqlite3.connect(self.path)) as db:
            reusable = previous.get("root") == str(root) and previous.get("parser_version") == PARSER_VERSION
            cached = {r[0]: (r[1], json.loads(r[2])) for r in db.execute("SELECT * FROM file_cache")} if reusable else {}
        records, calls, imports, warnings = [], [], {}, []
        cache_rows = []
        changed = unchanged = 0
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
            digest = hashlib.sha256(raw).hexdigest()
            old = cached.get(relative.as_posix())
            if old and old[0] == digest:
                parsed, pending, aliases, error = old[1]
                unchanged += 1
            else:
                parsed, pending, aliases, error = parse_file(relative, text)
                changed += 1
            cache_rows.append((relative.as_posix(), digest, json.dumps([parsed, pending, aliases, error])))
            records.extend(parsed)
            calls.extend(pending)
            imports[relative.as_posix()] = aliases
            digests[relative.as_posix()] = digest
            if error:
                warnings.append(error)
        edges, unresolved = resolve_calls(records, calls, imports)
        metadata = {"revision": uuid.uuid4().hex, "parser_version": PARSER_VERSION,
                    "changed_files": changed, "unchanged_files": unchanged,
                    "deleted_files": len(set(cached) - set(digests)), "root": str(root), "files": len(digests), "records": len(records), "edges": len(edges),
                    "warnings": warnings, "unresolved_calls": unresolved, "digests": digests}
        # One transaction replaces the snapshot; deletions cannot leave stale symbols or edges.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM file_cache")
            db.executemany("INSERT INTO file_cache VALUES(?,?,?)", cache_rows)
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

    def snapshot(self):
        """Read metadata, records, and edges from one consistent SQLite snapshot."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            row = db.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
            metadata = json.loads(row[0]) if row else {"revision": None, "files": 0, "records": 0, "edges": 0, "warnings": []}
            records = [json.loads(r[0]) for r in db.execute("SELECT payload FROM records ORDER BY id")]
            edges = [{"source": r[0], "target": r[1], "line": r[2]} for r in db.execute("SELECT * FROM edges ORDER BY source,target,line")]
            return metadata, records, edges
