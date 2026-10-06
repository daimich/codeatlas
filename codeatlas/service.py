import time
from collections import deque

from .indexer import Index
from .retrieval import Retriever


class Service:
    def __init__(self, db, semantic_model=None):
        self.index = Index(db)
        self.semantic_model = semantic_model
        self.retriever = Retriever(self.index.records(), semantic_model)
        self.records = {r["id"]: r for r in self.retriever.records}
        self.edges = self.index.graph()

    def search(self, question, k=5):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError("Question must have 1–2,000 characters")
        if type(k) is not int or not 1 <= k <= 20:
            raise ValueError("k must be an integer between 1 and 20")
        start = time.perf_counter()
        return {"hits": self.retriever.search(question, k),
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
        target = self.symbol(identifier)
        incoming = {}
        for edge in self.edges:
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
                    affected.append(dict(self.records[caller], distance=distance + 1))
        return {"symbol": target, "affected": affected, "depth": depth,
                "note": "Approximate static Python call graph; dynamic dispatch and external callers are not covered."}
