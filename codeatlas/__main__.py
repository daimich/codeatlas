import argparse
import json
from pathlib import Path

from .indexer import Index
from .service import Service
from .web import make_server


def main():
    parser = argparse.ArgumentParser(description="CodeAtlas repository intelligence")
    parser.add_argument("--db", default=".codeatlas/index.sqlite3")
    parser.add_argument("--semantic-model", help="Sentence Transformers model path or ID")
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    index.add_argument("path", type=Path)
    search = sub.add_parser("search")
    search.add_argument("question")
    search.add_argument("--k", type=int, default=5)
    impact = sub.add_parser("impact")
    impact.add_argument("symbol")
    impact.add_argument("--depth", type=int, default=3)
    sub.add_parser("status")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8081)
    serve.add_argument("--bind", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("--dataset", type=Path, default=Path("examples/evaluation.json"))
    args = parser.parse_args()
    try:
        if args.command == "index":
            result = Index(args.db).build(args.path)
            print(json.dumps({k: v for k, v in result.items() if k not in {"digests", "unresolved_calls"}}, indent=2))
            return
        service = Service(args.db, args.semantic_model)
        if args.command == "search":
            print(json.dumps(service.search(args.question, args.k), indent=2))
        elif args.command == "impact":
            print(json.dumps(service.impact(args.symbol, args.depth), indent=2))
        elif args.command == "status":
            print(json.dumps(service.index.metadata(), indent=2))
        elif args.command == "eval":
            results = []
            for case in json.loads(args.dataset.read_text()):
                hits = service.search(case["question"], 5)
                rank = next((i for i, hit in enumerate(hits["hits"], 1) if hit["qualified"] == case["symbol"]), None)
                results.append({"question": case["question"], "rank": rank, "latency_ms": hits["latency_ms"]})
            count = len(results)
            print(json.dumps({"queries": count, "recall_at_5": sum(r["rank"] is not None for r in results) / max(1, count),
                              "mrr_at_5": sum(1 / r["rank"] if r["rank"] else 0 for r in results) / max(1, count), "results": results}, indent=2))
        elif args.command == "serve":
            server = make_server(service, args.port, args.bind)
            print(f"CodeAtlas → http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
