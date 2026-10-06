"""Content-addressed dense vector cache; stores JSON, never executable pickles."""

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from .models import ModelError

MODEL_LOCK = threading.RLock()


@lru_cache(maxsize=2)
def encoder_for(model):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ModelError("Install semantic support: python -m pip install '.[semantic]'") from exc
    try:
        return SentenceTransformer(model, trust_remote_code=False)
    except Exception as exc:
        raise ModelError("Could not load the embedding model. Check its name, download access, or local directory.") from exc


def encode(model, texts):
    try:
        with MODEL_LOCK:
            encoder = encoder_for(model)
            vectors = encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in row] for row in vectors]
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError("Embedding inference failed; check the model and available memory") from exc


def vectors_for(model, texts, cache_path=None):
    if not texts:
        return []
    if cache_path is None:
        return encode(model, texts)
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    keys = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    vectors, missing = {}, {}
    with closing(sqlite3.connect(str(cache_path), timeout=30)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS embeddings (model TEXT, digest TEXT, vector TEXT, PRIMARY KEY(model,digest))")
        for key, text in zip(keys, texts):
            row = db.execute("SELECT vector FROM embeddings WHERE model=? AND digest=?", (model, key)).fetchone()
            try:
                value = json.loads(row[0]) if row else None
                if not isinstance(value, list) or not value or not all(type(v) in (int, float) and math.isfinite(v) for v in value):
                    raise ValueError("Invalid cached vector")
                vectors[key] = value
            except (ValueError, TypeError):
                missing[key] = text
        if missing:
            generated = encode(model, list(missing.values()))
            if len(generated) != len(missing):
                raise ModelError("Embedding model returned the wrong number of vectors")
            for key, vector in zip(missing, generated):
                vectors[key] = vector
                db.execute("INSERT OR REPLACE INTO embeddings VALUES(?,?,?)", (model, key, json.dumps(vector)))
    return [vectors[key] for key in keys]
