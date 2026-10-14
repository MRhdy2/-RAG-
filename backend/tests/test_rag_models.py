import asyncio
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch


SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "rag_service.py"


class FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def fake_module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def load_module():
    provider_calls = []

    def init_chat_model(**kwargs):
        provider_calls.append(kwargs)
        return kwargs

    modules = {
        "dotenv": fake_module("dotenv", load_dotenv=lambda **kwargs: None),
        "langchain": fake_module("langchain"),
        "langchain.chat_models": fake_module("langchain.chat_models", init_chat_model=init_chat_model),
        "langchain_openai": fake_module("langchain_openai", ChatOpenAI=FakeChatOpenAI),
        "langchain_community": fake_module("langchain_community"),
        "langchain_community.vectorstores": fake_module("langchain_community.vectorstores", FAISS=object),
        "typing_extensions": fake_module("typing_extensions", TypedDict=TypedDict),
        "services": fake_module("services"),
        "services.embedding_service": fake_module(
            "services.embedding_service",
            DEFAULT_BASE_URL="https://api.siliconflow.cn/v1",
            ensure_index_compatible=lambda path, vision_model: None,
            load_embeddings=lambda: None,
        ),
        "services.image_index_service": fake_module(
            "services.image_index_service", vision_model=lambda: "Qwen/Qwen3.6-35B-A3B"
        ),
    }
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("rag_service_test", SERVICE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, provider_calls


class RagModelTests(unittest.TestCase):
    def setUp(self):
        self.rag, self.provider_calls = load_module()

    def test_answers_use_deepseek_and_grading_uses_qwen(self):
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "siliconflow-key"}, clear=True):
            self.rag._get_llm()
            grader = self.rag._get_grader()

        self.assertEqual(self.provider_calls[0]["model"], "deepseek-chat")
        self.assertEqual(self.provider_calls[0]["model_provider"], "deepseek")
        self.assertEqual(grader.kwargs["model"], "Qwen/Qwen3.8-27B")
        self.assertEqual(grader.kwargs["api_key"], "siliconflow-key")
        self.assertEqual(grader.kwargs["base_url"], "https://api.siliconflow.cn/v1")

    def test_retrieval_uses_qwen_judgment_even_for_close_vector_match(self):
        calls = []

        class Grader:
            async def ainvoke(self, messages):
                calls.append(messages)
                return types.SimpleNamespace(content="no")

        document = types.SimpleNamespace(page_content="无关片段", metadata={})
        self.rag._load_vs = lambda file_id: types.SimpleNamespace(
            similarity_search_with_score=lambda question, k: [(document, 0.01)]
        )
        self.rag._get_grader = lambda: Grader()

        citations, context = asyncio.run(self.rag.retrieve("用户问题", "file-1"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(citations), 1)
        self.assertEqual(context, "")

    def test_retrieval_includes_image_description_and_direct_image_citation(self):
        class Grader:
            async def ainvoke(self, messages):
                return types.SimpleNamespace(content="yes")

        image_doc = types.SimpleNamespace(
            page_content="流程图展示了上传、解析和检索三个步骤",
            metadata={"kind": "image", "page": 2, "imagePath": "page2_img1.png"},
        )
        self.rag._load_vs = lambda file_id: types.SimpleNamespace(
            similarity_search_with_score=lambda question, k: [(image_doc, 0.1)]
        )
        self.rag._get_grader = lambda: Grader()

        citations, context = asyncio.run(self.rag.retrieve("流程图展示什么？", "file-1"))
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["kind"], "image")
        self.assertEqual(citations[0]["page"], 2)
        self.assertEqual(citations[0]["previewUrl"], citations[0]["imageUrl"])
        self.assertIn("上传、解析和检索", context)
        self.assertIn("page2_img1.png", context)


if __name__ == "__main__":
    unittest.main()
