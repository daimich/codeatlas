import time
import threading
from collections import deque

from .indexer import Index
from .retrieval import Retriever
from .answers import answer
from .models import model_status
from .embeddings import encode


class Service:
    def __init__(self, db, semantic_model=None, ollama_model=None, ollama_url="http://localhost:11434"):
        self.index = Index(db)
        self.semantic_model = semantic_model
        self.ollama_model, self.ollama_url = ollama_model, ollama_url
        self.cache_path = str(db) + ".vectors.sqlite3"
        self.lock = threading.RLock()
        self.retriever = None
        self.revision = None
        self.records, self.edges = {}, []

    def refresh(self):
        with self.lock:
            metadata = self.index.metadata()
            revision = metadata.get("revision", metadata.get("digests"))
            if self.retriever is None or self.revision != revision:
                meta, records, edges = self.index.snapshot()
                retriever = Retriever(records, self.semantic_model, self.cache_path)
                self.retriever, self.records, self.edges = retriever, {r["id"]: r for r in records}, edges
                self.revision = meta.get("revision", meta.get("digests"))

    def status(self, check=False):
        meta = self.index.metadata()
        result = {k: v for k, v in meta.items() if k not in {"root", "digests", "unresolved_calls"}}
        models = model_status(self.semantic_model, self.ollama_model, self.ollama_url, check)
        if check and self.semantic_model and models["semantic_dependency"]:
            try:
                encode(self.semantic_model, ["model readiness check"])
            except ValueError as exc:
                models["errors"].append(str(exc))
                models["ready"] = False
        return dict(result, **models, retrieval="bm25+dense+rrf" if self.semantic_model else "bm25",
                    generation="ollama" if self.ollama_model else "evidence", can_reindex=bool(meta.get("root")))

    def reindex(self):
        with self.lock:
            root = self.index.metadata().get("root")
            if not root:
                raise ValueError("Index a repository from the CLI first: python -m codeatlas index /path/to/repository")
            self.index.build(root)
            self.refresh()
            return self.status()

    def search(self, question, k=5):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Question must have 1–2,000 characters")
        if type(k) is not int or not 1 <= k <= 20:
            raise ValueError("k must be an integer between 1 and 20")
        start = time.perf_counter()
        with self.lock:
            self.refresh()
            hits = self.retriever.search(question, k)
        return {"hits": hits,
                "latency_ms": round(1000 * (time.perf_counter() - start), 2),
                "retrieval": "bm25+dense+rrf" if self.semantic_model else "bm25"}

    def symbol(self, identifier):
        if identifier in self.records:
            return self.records[identifier]
        matches = [r for r in self.records.values() if r["qualified"] == identifier or r["name"] == identifier]
        if not matches:
            raise ValueError("Symbol not found; use an exact symbol id from search")
        if len(matches) > 1:
            raise ValueError("Ambiguous symbol; use an exact symbol id from search")
        return matches[0]

    def impact(self, identifier, depth=3):
        if not isinstance(identifier, str):
            raise ValueError("symbol must be a string")
        if type(depth) is not int or not 1 <= depth <= 10:
            raise ValueError("depth must be an integer between 1 and 10")
        with self.lock:
            self.refresh()
            target = self.symbol(identifier)
            # Retain one immutable snapshot even if another request reindexes.
            records, edges = self.records, self.edges
        incoming = {}
        for edge in edges:
            incoming.setdefault(edge["target"], set()).add(edge["source"])
        visited = {target["id"]}
        queue = deque([(target["id"], 0)])
        affected = []
        while queue:
            current, distance = queue.popleft()
            if distance >= depth:
                continue
            for caller in sorted(incoming.get(current, [])):
                if caller not in visited:
                    visited.add(caller)
                    queue.append((caller, distance + 1))
                    affected.append(dict(records[caller], distance=distance + 1))
        return {"symbol": target, "affected": affected, "depth": depth,
                "note": "Approximate static Python call graph; dynamic dispatch and external callers are not covered."}

    def ask(self, question, k=5):
        start = time.perf_counter()
        found = self.search(question, k)
        return dict(answer(question, found["hits"], self.ollama_model, self.ollama_url),
                    latency_ms=found["latency_ms"], total_ms=round(1000 * (time.perf_counter() - start), 2),
                    retrieval=found["retrieval"])
