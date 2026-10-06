import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from codeatlas.indexer import Index, parse_file, source_files
from codeatlas.service import Service
from codeatlas.web import make_server


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.db = Path(self.temp.name) / "index.db"
        self.index = Index(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_qualified_symbols_and_import_call_edges(self):
        self.write("auth.py", "def verify_token(t):\n return t\n")
        self.write("api.py", "from auth import verify_token as check\ndef handler():\n return check('x')\n")
        result = self.index.build(self.root)
        self.assertEqual(result["edges"], 1)
        service = Service(self.db)
        self.assertEqual(service.impact("auth.verify_token")["affected"][0]["qualified"], "api.handler")

    def test_relative_package_import(self):
        self.write("pkg/__init__.py", "")
        self.write("pkg/util.py", "def helper():\n return 1\n")
        self.write("pkg/api.py", "from .util import helper\ndef handler():\n return helper()\n")
        self.index.build(self.root)
        self.assertEqual(Service(self.db).impact("pkg.util.helper")["affected"][0]["qualified"], "pkg.api.handler")

    def test_method_and_nested_function_ranges(self):
        records, calls, _, error = parse_file(Path("x.py"), "class A:\n def get(self):\n  return 1\n def fetch(self):\n  return self.get()\n")
        self.assertIsNone(error)
        self.assertIn("x.A.get", [r["qualified"] for r in records])
        self.assertEqual(next(r for r in records if r["qualified"] == "x.A.fetch")["start"], 4)
        self.write("x.py", "class A:\n def get(self):\n  return 1\n def fetch(self):\n  return self.get()\n")
        self.index.build(self.root)
        self.assertEqual(Service(self.db).impact("x.A.get")["affected"][0]["qualified"], "x.A.fetch")

    def test_rebuild_removes_deleted_symbols(self):
        self.write("x.py", "def deleted():\n pass\n")
        self.index.build(self.root)
        (self.root / "x.py").unlink()
        self.index.build(self.root)
        self.assertEqual(self.index.records(), [])
        self.assertEqual(self.index.graph(), [])

    def test_syntax_error_and_nonpython_fallback(self):
        self.write("broken.py", "def x(\n")
        self.write("app.ts", "export function authenticateRequest() { return 'ok'; }")
        result = self.index.build(self.root)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertTrue(all(r["kind"] == "text" for r in self.index.records()))
        self.assertEqual(Service(self.db).search("authenticate request")["hits"][0]["path"], "app.ts")

    def test_symlinks_and_sensitive_paths_are_excluded(self):
        self.write("safe.py", "print('safe')")
        self.write("credentials.py", "SECRET = 'demo'")
        self.write("node_modules/dependency.py", "print('skip')")
        external = Path(self.temp.name) / "outside.py"
        external.write_text("print('external')")
        (self.root / "link.py").symlink_to(external)
        self.assertEqual([p.name for p in source_files(self.root)], ["safe.py"])

    def test_gitignore_respected(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "ignored.py\n")
        self.write("ignored.py", "print('skip')")
        self.write("included.py", "print('keep')")
        self.assertEqual([p.name for p in source_files(self.root)], ["included.py"])

    def test_cycle_safe_impact_and_depth(self):
        self.write("x.py", "def a():\n return b()\ndef b():\n return a()\ndef c():\n return b()\n")
        self.index.build(self.root)
        service = Service(self.db)
        self.assertEqual({r["qualified"] for r in service.impact("x.a", 3)["affected"]}, {"x.b", "x.c"})
        self.assertEqual([r["qualified"] for r in service.impact("x.a", 1)["affected"]], ["x.b"])

    def test_ambiguous_symbol_not_silently_selected(self):
        self.write("a.py", "def run():\n pass\n")
        self.write("b.py", "def run():\n pass\n")
        self.index.build(self.root)
        with self.assertRaises(ValueError):
            Service(self.db).impact("run")

    def test_sample_retrieval_and_transitive_callers(self):
        root = Path(__file__).resolve().parents[1]
        self.index.build(root / "examples/sample_repo")
        service = Service(self.db)
        for case in json.loads((root / "examples/evaluation.json").read_text()):
            with self.subTest(question=case["question"]):
                self.assertIn(case["symbol"], [r["qualified"] for r in service.search(case["question"])["hits"]])
        self.assertEqual({r["qualified"] for r in service.impact("auth.verify_token")["affected"]},
                         {"auth.authenticate_request", "api.handle_invoice"})

    def test_indexing_never_executes_repository_code(self):
        marker = Path(self.temp.name) / "should-not-exist"
        self.write("danger.py", f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        self.index.build(self.root)
        self.assertFalse(marker.exists())

    def test_input_limits(self):
        service = Service(self.db)
        with self.assertRaises(ValueError):
            service.search(None)
        with self.assertRaises(ValueError):
            service.impact("missing", 100)


class HttpTests(unittest.TestCase):
    def test_http_search_and_origin_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "index.db"
            Index(db).build(Path(__file__).resolve().parents[1] / "examples/sample_repo")
            server = make_server(Service(db), 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/search"
                request = urllib.request.Request(url, data=b'{"question":"verify token"}', headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request) as response:
                    self.assertTrue(json.load(response)["hits"])
                request.add_header("Origin", "https://evil.example")
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
