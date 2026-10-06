"""Small-corpus BM25 and optional dense retrieval with reciprocal rank fusion."""

import math
import re
from collections import Counter

STOP = set("a an the is are was were to of for on in and or with what which where how do does can be it this that from by as at".split())


def tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


class Retriever:
    def __init__(self, records, model=None):
        self.records = records
        self.counts = [Counter(tokens(r["search_text"])) for r in records]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = sum(self.lengths) / max(1, len(records))
        self.df = Counter(t for c in self.counts for t in c)
        self.encoder = None
        self.vectors = None
        if model and records:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ValueError("Install the semantic extra: pip install '.[semantic]'") from exc
            self.encoder = SentenceTransformer(model, trust_remote_code=False)
            self.vectors = self.encoder.encode(
                [r["search_text"] for r in records], normalize_embeddings=True
            )

    def search(self, query, k=5):
        query_tokens = set(tokens(query))
        if not query_tokens:
            return []
        scores = []
        for i, counts in enumerate(self.counts):
            score = 0.0
            for token in query_tokens:
                frequency = counts[token]
                if frequency:
                    idf = math.log(1 + (len(self.records) - self.df[token] + 0.5) / (self.df[token] + 0.5))
                    denominator = frequency + 1.5 * (0.25 + 0.75 * self.lengths[i] / max(1, self.average))
                    score += idf * frequency * 2.5 / denominator
            if score > 0:
                scores.append((i, score))
        lexical = sorted(scores, key=lambda x: (-x[1], self.records[x[0]]["id"]))
        ranks = {i: 1 / (60 + rank) for rank, (i, _) in enumerate(lexical, 1)}
        dense_scores = {}
        if self.encoder is not None:
            vector = self.encoder.encode([query], normalize_embeddings=True)[0]
            dense_scores = {i: float(v @ vector) for i, v in enumerate(self.vectors)}
            dense = sorted(dense_scores.items(), key=lambda x: (-x[1], x[0]))
            for rank, (i, score) in enumerate(dense[:50], 1):
                if score >= 0.2:
                    ranks[i] = ranks.get(i, 0) + 1 / (60 + rank)
        lexical_scores = dict(lexical)
        ordered = sorted(ranks, key=lambda i: (-ranks[i], self.records[i]["id"]))[:k]
        return [dict(self.records[i], score=round(ranks[i], 6),
                     bm25=round(lexical_scores.get(i, 0), 4),
                     cosine=round(dense_scores[i], 4) if i in dense_scores else None)
                for i in ordered]
