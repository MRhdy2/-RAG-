import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "embedding_service.py"


class FakeOpenAIEmbeddings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def load_module():
    fake_langchain_openai = types.ModuleType("langchain_openai")
    fake_langchain_openai.OpenAIEmbeddings = FakeOpenAIEmbeddings
    with patch.dict(sys.modules, {"langchain_openai": fake_langchain_openai}):
        spec = importlib.util.spec_from_file_location("embedding_service_test", SERVICE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class EmbeddingServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = load_module()

    def test_uses_siliconflow_key_endpoint_and_model(self):
        env = {
            "OPENAI_API_KEY": "unused-openai-key",
            "OPENAI_BASE_URL": "https://unused.example/v1",
            "SILICONFLOW_API_KEY": "siliconflow-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = self.service.load_embeddings().kwargs
        self.assertEqual(config["api_key"], "siliconflow-key")
        self.assertEqual(config["base_url"], "https://api.siliconflow.cn/v1")
        self.assertEqual(config["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertFalse(config["check_embedding_ctx_length"])
        self.assertEqual(config["encoding_format"], "float")

    def test_openai_key_does_not_replace_missing_siliconflow_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unused-openai-key"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SILICONFLOW_API_KEY"):
                self.service.load_embeddings()

    def test_requires_rebuild_when_model_changes_or_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(self.service.IndexRebuildRequiredError):
                    self.service.ensure_index_compatible(index_path)
                self.service.save_index_metadata(index_path)
                self.service.ensure_index_compatible(index_path)
                metadata = json.loads((index_path / "embedding.json").read_text())
                self.assertEqual(metadata["model"], "Qwen/Qwen3-Embedding-8B")

            with patch.dict(os.environ, {"SILICONFLOW_EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-4B"}, clear=True):
                with self.assertRaises(self.service.IndexRebuildRequiredError):
                    self.service.ensure_index_compatible(index_path)


if __name__ == "__main__":
    unittest.main()
