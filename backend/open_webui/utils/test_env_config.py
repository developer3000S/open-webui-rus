"""Tests for open_webui/utils/env_config.py.

Loaded by file path rather than imported as `open_webui.utils.*` so these run on a bare
host without the application's dependencies (`open_webui/__init__.py` imports typer).

Run with either:
    python3 -m unittest discover -s backend/open_webui/utils -p 'test_*.py'
    cd backend && pytest open_webui/utils/test_env_config.py
"""

import importlib.util
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location('env_config', str(Path(__file__).resolve().parent / 'env_config.py'))
env_config = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(env_config)

_ENV_TEXT = """\
# comment
OLLAMA_BASE_URL='http://host.docker.internal:11434'

  RAG_EMBEDDING_BATCH_SIZE=1   # inline comment
export VECTOR_DB=chroma
EMPTY_ON_PURPOSE=
NOT_AN_ASSIGNMENT
"""


class ParseEnvFileTest(unittest.TestCase):
    def test_returns_names_with_unquoted_values(self) -> None:
        values = env_config.parse_env_file(_ENV_TEXT)
        self.assertEqual(
            values,
            {
                'OLLAMA_BASE_URL': 'http://host.docker.internal:11434',
                'RAG_EMBEDDING_BATCH_SIZE': '1',
                'VECTOR_DB': 'chroma',
                'EMPTY_ON_PURPOSE': '',
            },
        )

    def test_declared_key_with_empty_value_still_counts(self) -> None:
        """ "KEY=" is an explicit statement the setting is empty, not an absence."""
        self.assertIn('EMPTY_ON_PURPOSE', env_config.parse_env_file('EMPTY_ON_PURPOSE=\n'))

    def test_keeps_spaces_inside_quotes(self) -> None:
        """A reranker model id is stored with a trailing space; quotes must not eat it."""
        parsed = env_config.parse_env_file("M='qllama/bge:latest '\n")
        self.assertEqual(parsed['M'], 'qllama/bge:latest ')

    def test_docker_env_file_quoting_is_normalised(self) -> None:
        """`docker run --env-file` leaves the quotes in the value, compose strips them."""
        self.assertEqual(env_config.unquote("'http://x:11434'"), env_config.unquote('http://x:11434'))

    def test_later_line_wins(self) -> None:
        self.assertEqual(env_config.parse_env_file('A=1\nA=2\n'), {'A': '2'})


class DeclaredNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        env_config.reset_declared()
        self.addCleanup(env_config.reset_declared)

    def test_env_bound_requires_the_name_to_be_declared(self) -> None:
        self.assertFalse(env_config.is_declared_in_env('rag.embedding_batch_size'))
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        self.assertTrue(env_config.is_declared_in_env('rag.embedding_batch_size'))
        self.assertFalse(env_config.is_declared_in_env('rag.embedding_model'))

    def test_env_name_for_maps_dotted_keys(self) -> None:
        self.assertEqual(env_config.env_name_for('rag.embedding_batch_size'), 'RAG_EMBEDDING_BATCH_SIZE')

    def test_read_env_file_records_and_reports_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(_ENV_TEXT, encoding='utf-8')
            names = env_config.read_env_file(path)
        self.assertIn('OLLAMA_BASE_URL', names)
        self.assertTrue(env_config.is_declared_in_env('rag.embedding_batch_size'))

    def test_missing_file_declares_nothing(self) -> None:
        self.assertEqual(env_config.read_env_file(Path('/nonexistent/dir/.env')), set())
        env_config.record_declared({'A'})
        env_config.read_env_file(Path('/nonexistent/dir/.env'))
        self.assertEqual(env_config.declared_names(), frozenset({'A'}))


class EnvBoundIsNotInheritedEnvironmentTest(unittest.TestCase):
    def test_inherited_image_env_does_not_bind_a_key(self) -> None:
        """The image ships RAG_EMBEDDING_MODEL for the build-time model download. If merely
        having it in os.environ bound the config key, that baked-in value would override
        whatever the admin saved -- the exact failure this distinction prevents."""
        env_config.reset_declared()
        self.addCleanup(env_config.reset_declared)
        with mock.patch.dict('os.environ', {'RAG_EMBEDDING_MODEL': 'sentence-transformers/all-MiniLM-L6-v2'}):
            self.assertFalse(env_config.is_declared_in_env('rag.embedding_model'))


class ShellExportSafetyTest(unittest.TestCase):
    """backend/start.sh feeds parse_env_file() output into generated `export K=...`
    statements. Two consumers of one file (the shell launcher and env.py) must not
    disagree, so the shape the shell relies on is asserted instead of left implicit.
    """

    def test_names_are_valid_shell_identifiers(self) -> None:
        for name in env_config.parse_env_file(_ENV_TEXT):
            self.assertTrue(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name), name)

    def test_values_never_contain_newlines(self) -> None:
        """A newline would break out of the export statement it is interpolated into."""
        for value in env_config.parse_env_file(_ENV_TEXT).values():
            self.assertNotIn('\n', value)

    def test_metacharacters_survive_a_sh_round_trip(self) -> None:
        """Values are passed through unexpanded and re-quoted, never eval'd: a payload
        that looks like a command must arrive as literal text."""
        nasty = "a b; echo pwned | wc -c `id` $(id) 'q' * $HOME"
        values = env_config.parse_env_file(f'SHELL_UNSAFE="{nasty}"\n')
        statement = ''.join(f'export {k}={shlex.quote(v)}\n' for k, v in values.items())
        result = subprocess.run(
            ['sh', '-c', f'{statement}printf "%s" "$SHELL_UNSAFE"'],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout, nasty)


class ParityWithDotenvTest(unittest.TestCase):
    """env.py loads the file through python-dotenv while start.sh uses this parser.

    Two readers of one file must not disagree, and the corpus is exactly the syntax
    the real .env uses, so drift in either direction is caught here. Skipped where
    python-dotenv is not installed.
    """

    CORPUS = """\
# a comment
OLLAMA_BASE_URL='http://host.docker.internal:11434'
OPENAI_API_KEY=example-not-a-real-key
CORS_ALLOW_ORIGIN='*'
FORWARDED_ALLOW_IPS='*'
RAG_EMBEDDING_BATCH_SIZE=1   # inline comment
RAG_EMBEDDING_MODEL="qwen3-embedding:0.6b"
RAG_RERANKING_MODEL='qllama/bge-reranker-v2-m3:latest'
EMPTY_ON_PURPOSE=
TRANSFORMERS_NO_ADVISORY_WARNINGS=1
"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from dotenv import dotenv_values
        except ModuleNotFoundError:
            raise unittest.SkipTest('python-dotenv not installed on this host')
        cls.dotenv_values = staticmethod(dotenv_values)

    def test_same_values_as_python_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(self.CORPUS, encoding='utf-8')
            reference = {k: v for k, v in self.dotenv_values(path).items() if v is not None}
        self.assertEqual(env_config.parse_env_file(self.CORPUS), reference)

    def test_every_name_declared_by_dotenv_is_declared_here(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(self.CORPUS, encoding='utf-8')
            reference = set(self.dotenv_values(path))
        self.assertEqual(set(env_config.parse_env_file(self.CORPUS)), reference)


if __name__ == '__main__':
    unittest.main()
