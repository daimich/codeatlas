# Validation

The completion target is a dependable single-user local application. These checks exercise the documented workflows; they do not establish enterprise readiness or general AI accuracy. Consult the latest GitHub Actions run for the exact commit being used.

| Check | Coverage |
|---|---|
| Unit/regression tests | 26 tests; Python 3.11, 3.12 and 3.13 in CI |
| Browser acceptance | Actual Chromium UI interactions, persistence/refresh, empty states, browser errors |
| Docker acceptance | Image startup, real HTTP endpoints, named-volume replacement, deletion/refresh |
| Real-model acceptance | Actual MiniLM embeddings, persisted vectors, Ollama Qwen 2.5 1.5B generation over HTTP, valid citations, fixture answer content and abstention for absent facts |
| Toy evaluation | Six committed retrieval queries; Recall@5 and MRR@5 |

## Reproduce

```bash
python -m unittest discover -s tests -v
python -m pip install playwright==1.58.0
python -m playwright install --with-deps chromium
python scripts/test_browser.py
docker build -t codeatlas:test .
python scripts/test_docker.py codeatlas:test
```

Real models require installed semantic dependencies, a running Ollama service and pulled weights:

```bash
python -m pip install '.[semantic]'
ollama pull qwen2.5:1.5b
python scripts/test_live_models.py
```

The test accepts `--semantic-model`, `--ollama-model`, and `--ollama-url`. It uses temporary fixture data, checks real model readiness, restarts the application service against the persisted index, and calls the actual answer API. It must produce a non-abstaining answer containing the expected fixture fact and valid source references; merely returning HTTP 200 does not pass. A separate question about an absent fact must abstain.

The **CI** workflow runs unit, browser and default Docker checks on every push/PR. **Real models** runs for relevant model-code changes on main or by manual dispatch, with its generated response saved as an Actions artifact. The optional Compose AI profile is documented but is not a separate tested deployment target; its model adapters are exercised by Real models. Large-corpus performance, adversarial answer quality and cross-platform native execution are not established by these checks.
