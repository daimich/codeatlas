"""Source-cited code explanations using optional local generation."""

from .models import generate_claims


def answer(question, hits, model=None, endpoint="http://localhost:11434"):
    evidence = [dict({k: hit[k] for k in ("id", "path", "start", "end", "text", "qualified")},
                     kind=hit.get("kind", "source")) for hit in hits]
    if not evidence:
        return {"mode": "evidence", "abstained": True, "claims": [], "evidence": []}
    if not model:
        return {"mode": "evidence", "abstained": False, "claims": [], "evidence": evidence}
    generated = generate_claims(question, evidence, model, endpoint)
    by_id = {item["id"]: item for item in evidence}
    claims = []
    for claim in generated["claims"]:
        source = by_id[claim["citation"]]
        claims.append(dict(claim, path=source["path"], start=source["start"],
                           end=source["start"] + len(claim["quote"].splitlines()) - 1))
    return {"mode": "ollama", "abstained": generated["abstain"], "claims": claims, "evidence": evidence}
