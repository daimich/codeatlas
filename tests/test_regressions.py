import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codeatlas.indexer import Index
from codeatlas.service import Service
from codeatlas.models import generate_claims, ModelError
from codeatlas.embeddings import vectors_for


class IndexRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.db = Path(self.temp.name) / 'index.db'
        self.index = Index(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def test_repeated_definitions_do_not_crash_or_resolve_ambiguously(self):
        self.write('a.py', 'def run():\n return 1\ndef run():\n return 2\ndef caller():\n return run()\n')
        self.index.build(self.root)
        records = [r for r in self.index.records() if r['kind'] == 'function']
        self.assertEqual(len(records), 3)
        self.assertEqual(len({r['id'] for r in records}), 3)
        self.assertEqual(self.index.graph(), [])

    def test_parameter_shadowing_and_class_scope_are_not_false_edges(self):
        self.write('a.py', 'def helper():\n return 1\ndef caller(helper):\n return helper()\nclass A:\n def run(self):\n  return 2\n def other(self):\n  return run()\n')
        self.index.build(self.root)
        self.assertEqual(self.index.graph(), [])

    def test_function_import_does_not_leak_into_other_function(self):
        self.write('a.py', 'def run():\n return 1\n')
        self.write('b.py', 'def first():\n from a import run\n return run()\ndef second():\n return run()\n')
        self.index.build(self.root)
        edges = self.index.graph()
        self.assertEqual(len(edges), 1)
        self.assertIn('b.first', edges[0]['source'])

    def test_nested_function_uses_enclosing_lexical_binding(self):
        self.write('a.py', 'def outer():\n def helper():\n  return 1\n def inner():\n  return helper()\n return inner()\n')
        self.index.build(self.root)
        affected = Service(self.db).impact('a.outer.helper')['affected']
        self.assertEqual({r['qualified'] for r in affected}, {'a.outer.inner', 'a.outer'})

    def test_src_layout_and_package_reexport(self):
        self.write('src/pkg/core.py', 'def run():\n return 1\n')
        self.write('src/pkg/__init__.py', 'from .core import run\n')
        self.write('src/pkg/api.py', 'from pkg import run\ndef caller():\n return run()\n')
        self.index.build(self.root)
        affected = Service(self.db).impact('pkg.core.run')['affected']
        self.assertEqual([r['qualified'] for r in affected], ['pkg.api.caller'])

    def test_all_module_lines_are_searchable(self):
        self.write('long.py', '\n' * 160 + "ZEBRACONFIG = 'enabled'\n")
        self.index.build(self.root)
        hit = Service(self.db).search('ZEBRACONFIG')['hits'][0]
        self.assertIn('ZEBRACONFIG', hit['text'])
        self.assertGreater(hit['end'], 120)

    def test_live_reload_and_incremental_deletion(self):
        self.write('a.py', 'def before():\n return 1\n')
        self.write('b.py', 'def keep():\n return 2\n')
        first = self.index.build(self.root)
        service = Service(self.db)
        self.assertTrue(service.search('before')['hits'])
        self.write('a.py', 'def zebra():\n return 3\n')
        second = self.index.build(self.root)
        self.assertEqual((second['changed_files'], second['unchanged_files']), (1, 1))
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertTrue(service.search('zebra')['hits'])
        self.assertEqual(service.search('before')['hits'], [])
        (self.root / 'a.py').unlink()
        third = service.reindex()
        self.assertEqual(third['deleted_files'], 1)
        self.assertEqual(service.search('zebra')['hits'], [])

    def test_incremental_reindex_does_not_reparse_unchanged_files(self):
        self.write('a.py', 'def run():\n return 1\n')
        self.index.build(self.root)
        with patch('codeatlas.indexer.parse_file', side_effect=AssertionError('unchanged file reparsed')):
            self.index.build(self.root)

    def test_empty_workspace_has_actionable_reindex_error(self):
        with self.assertRaisesRegex(ValueError, 'Index a repository'):
            Service(self.db).reindex()


class ModelTests(unittest.TestCase):
    def test_generated_explanation_has_exact_source_locations(self):
        from codeatlas.answers import answer
        hit = {'id': 'x', 'path': 'a.py', 'start': 10, 'end': 12, 'qualified': 'a.run', 'text': 'def run():\n    return 1'}
        with patch('codeatlas.models.model_request', return_value={'message': {'content': json.dumps({'claims': [{'text': 'Returns one.', 'citation': 'S1'}]})}}):
            result = answer('What does run do?', [hit], 'model')
        self.assertEqual(result['claims'][0]['quote'], hit['text'])
        self.assertEqual((result['claims'][0]['start'], result['claims'][0]['end']), (10, 11))

    def test_unknown_model_citations_are_rejected_after_bounded_retry(self):
        evidence = [{'id': 'x', 'text': 'Payment is due after thirty days.'}]
        with patch('codeatlas.models.model_request', return_value={'message': {'content': json.dumps({'claims': [{'text': 'Wrong', 'citation': 'S9'}]})}}) as request:
            with self.assertRaises(ModelError):
                generate_claims('When?', evidence, 'model', 'http://localhost:11434')
        self.assertEqual(request.call_count, 2)

    def test_empty_model_claims_abstain_without_redundant_flag(self):
        with patch('codeatlas.models.model_request', return_value={'message': {'content': '{"claims": []}'}}):
            result = generate_claims('Who?', [{'id': 'x', 'text': 'No named person.'}], 'model', 'http://localhost:11434')
        self.assertEqual(result, {'abstain': True, 'claims': []})

    def test_persistent_vector_cache_reuses_content_and_models_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'vectors.db'
            with patch('codeatlas.embeddings.encode', side_effect=lambda model, texts: [[1.0, 0.0] for _ in texts]) as encoder:
                vectors_for('one', ['alpha', 'beta'], cache)
                vectors_for('one', ['alpha', 'beta'], cache)
                vectors_for('one', ['alpha', 'changed'], cache)
                self.assertEqual(encoder.call_count, 2)
                self.assertEqual(encoder.call_args.args[1], ['changed'])
                vectors_for('two', ['alpha'], cache)
                self.assertEqual(encoder.call_count, 3)


if __name__ == '__main__':
    unittest.main()
