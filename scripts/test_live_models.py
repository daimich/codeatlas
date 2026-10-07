"""Opt-in acceptance test using real embeddings and an already pulled Ollama model."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codeatlas.indexer import Index
from codeatlas.service import Service
from codeatlas.web import make_server
from codeatlas import models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--semantic-model', default='sentence-transformers/all-MiniLM-L6-v2')
    parser.add_argument('--ollama-model', default='qwen2.5:1.5b')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    # Observe actual fixture-model responses without replacing inference.
    request_model = models.model_request
    def record_request(*positional, **keywords):
        response = request_model(*positional, **keywords)
        if positional[1] == '/api/chat':
            print('Real Ollama response: ' + json.dumps({k: response.get(k) for k in ('message', 'done', 'done_reason')}), file=sys.stderr)
        return response
    models.model_request = record_request
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / 'repo'
        root.mkdir()
        (root / 'retry.py').write_text('def retry_delay_seconds():\n    """Return the fixed delay before retrying a failed request."""\n    return 7\n\ndef retry():\n    return retry_delay_seconds()\n')
        db = Path(folder) / 'index.sqlite3'
        Index(db).build(root)
        service = Service(db, args.semantic_model, args.ollama_model, args.ollama_url)
        question = 'What retry delay in seconds does retry_delay_seconds return?'
        health = service.status(check=True)
        assert health['ready'], health
        assert any(hit['qualified'] == 'retry.retry_delay_seconds' for hit in service.search(question)['hits'])
        assert service.impact('retry.retry_delay_seconds')['affected'][0]['qualified'] == 'retry.retry'
        with sqlite3.connect(str(db) + '.vectors.sqlite3') as cache:
            assert cache.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0] > 0
        restarted = Service(db, args.semantic_model, args.ollama_model, args.ollama_url)
        server = make_server(restarted, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/ask',
                data=json.dumps({'question': question, 'k': 3}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise AssertionError(exc.read().decode()) from exc
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        assert result['mode'] == 'ollama' and not result['abstained'], result
        by_id = {item['id']: item for item in result['evidence']}
        assert result['claims']
        for claim in result['claims']:
            source = by_id[claim['citation']]
            assert claim['quote'] in source['text']
            assert claim['path'] == 'retry.py' and claim['start'] == source['start']
            assert claim['end'] == source['start'] + len(claim['quote'].splitlines()) - 1
        answer = ' '.join(item['text'] for item in result['claims']).lower()
        assert 'seven' in answer or '7' in answer, result
        unsupported = models.generate_claims("What is the author's email address?", result['evidence'], args.ollama_model, args.ollama_url)
        assert unsupported == {'abstain': True, 'claims': []}, unsupported
        print(json.dumps({'passed': True, 'semantic_model': args.semantic_model,
                          'ollama_model': args.ollama_model, 'result': result}, indent=2))


if __name__ == '__main__':
    main()
