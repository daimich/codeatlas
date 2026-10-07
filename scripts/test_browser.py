"""Browser acceptance: python -m pip install playwright; playwright install chromium."""
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from playwright.sync_api import sync_playwright, expect

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from codeatlas.service import Service
from codeatlas.web import make_server


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / 'repo'
        shutil.copytree(PROJECT / 'examples/sample_repo', root)
        service = Service(Path(folder) / 'index.sqlite3')
        service.index.build(root)
        server = make_server(service, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#count')).to_have_text('4 files indexed')
                page.locator('#query').fill('Validate bearer token')
                page.locator('#submit').click()
                target = page.locator('.card').filter(has=page.get_by_text('auth.verify_token', exact=True))
                expect(target).to_be_visible()
                target.get_by_role('button', name='Trace callers').click()
                expect(page.locator('#mode')).to_have_text('Impact of auth.verify_token')
                expect(page.locator('#results')).to_contain_text('auth.authenticate_request')
                expect(page.locator('#results')).to_contain_text('api.handle_invoice')
                page.locator('#answer-mode').select_option('ask')
                page.locator('#submit').click()
                expect(page.locator('#mode')).to_have_text('Source evidence')
                expect(page.locator('#results')).to_contain_text('example-token')
                expect(page.locator('#results .trace').first).to_be_visible()
                # Exercise presentation of a valid abstention using the real retrieved evidence.
                def abstain(route):
                    response = route.fetch()
                    payload = dict(response.json(), mode='ollama', abstained=True, claims=[])
                    route.fulfill(response=response, json=payload)
                page.route('**/api/ask', abstain)
                page.locator('#submit').click()
                expect(page.locator('#mode')).to_have_text('Source evidence · model abstained')
                expect(page.locator('#results')).to_contain_text('example-token')
                page.unroute('**/api/ask', abstain)
                (root / 'new.py').write_text('def zebracounter():\n    return 42\n')
                page.locator('#reindex').click()
                expect(page.locator('#count')).to_have_text('5 files indexed')
                expect(page.locator('#status')).to_contain_text('1 changed')
                page.locator('#answer-mode').select_option('search')
                page.locator('#query').fill('zebracounter')
                page.locator('#submit').click()
                expect(page.locator('#results')).to_contain_text('new.zebracounter')
                (root / 'new.py').unlink()
                page.locator('#reindex').click()
                expect(page.locator('#count')).to_have_text('4 files indexed')
                page.locator('#submit').click()
                expect(page.locator('#results')).to_contain_text('No matching code')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
    print('PASS: search, caller graph, source explanations, abstention evidence, incremental refresh, deletion, no browser errors')


if __name__ == '__main__':
    main()
