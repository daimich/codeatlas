"""BM25 with an inverted index, cached dense vectors, and reciprocal rank fusion."""

import math
import re
from collections import Counter, defaultdict

from .embeddings import encode, vectors_for
from .models import ModelError

STOP = set("a an the is are was were to of for on in and or with what which where how do does can be it this that from by as at".split())


def tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return [t for t in re.findall(r"[^\W_]+", text.lower()) if t not in STOP]


class Retriever:
    def __init__(self, records, model=None, cache_path=None):
        self.records = records
        self.model = model
        self.lengths = []
        self.postings = defaultdict(list)
        for i, record in enumerate(records):
            counts = Counter(tokens(record["search_text"]))
            self.lengths.append(sum(counts.values()))
            for token, frequency in counts.items():
                self.postings[token].append((i, frequency))
        self.average = sum(self.lengths) / max(1, len(records))
        self.vectors = vectors_for(model, [r["search_text"] for r in records], cache_path) if model else None

    def search(self, query, k=5):
        query_tokens = set(tokens(query))
        if not query_tokens:
            return []
        scores = defaultdict(float)
        for token in query_tokens:
            matches = self.postings.get(token, [])
            idf = math.log(1 + (len(self.records) - len(matches) + 0.5) / (len(matches) + 0.5))
            for i, frequency in matches:
                denominator = frequency + 1.5 * (0.25 + 0.75 * self.lengths[i] / max(1, self.average))
                scores[i] += idf * frequency * 2.5 / denominator
        lexical = sorted(scores, key=lambda i: (-scores[i], self.records[i]["id"]))
        ranks = {i: 1 / (60 + rank) for rank, i in enumerate(lexical[:50], 1)}
        dense_scores = {}
        if self.model and self.records:
            vector = encode(self.model, [query])[0]
            for i, stored in enumerate(self.vectors):
                if len(stored) != len(vector):
                    raise ModelError("Embedding dimensions changed. Remove the .vectors.sqlite3 cache and retry.")
                dense_scores[i] = sum(a * b for a, b in zip(stored, vector))
            dense = sorted(dense_scores, key=lambda i: (-dense_scores[i], self.records[i]["id"]))
            for rank, i in enumerate(dense[:50], 1):
                if dense_scores[i] >= 0.2:
                    ranks[i] = ranks.get(i, 0) + 1 / (60 + rank)
        ordered = sorted(ranks, key=lambda i: (-ranks[i], self.records[i]["id"]))[:k]
        return [dict(self.records[i], score=round(ranks[i], 6), bm25=round(scores.get(i, 0), 4),
                     cosine=round(dense_scores[i], 4) if i in dense_scores else None) for i in ordered]
