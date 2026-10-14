import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.embeddings import Embeddings
from PIL import Image

from services import image_index_service, index_service, pdf_service


class FakeSiliconFlowClient:
    def __init__(self):
        self.chat_requests = []
        self.embedding_requests = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.describe))
        self.embeddings = types.SimpleNamespace(create=self.embed)

    def describe(self, **kwargs):
        self.chat_requests.append(kwargs)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="红色流程图，展示文档解析到检索的步骤。")
        )])

    def embed(self, **kwargs):
        self.embedding_requests.append(kwargs)
        return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[1.0, 0.0])])


class FakeTextEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0, 1.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0] if "流程图" in text else [0.0, 1.0]


class UnifiedIndexTests(unittest.TestCase):
    def test_vision_description_retries_empty_response_without_thinking(self):
        client = FakeSiliconFlowClient()
        responses = ["", "图中展示了三个处理步骤。"]

        def describe(**kwargs):
            client.chat_requests.append(kwargs)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                finish_reason="stop",
                message=types.SimpleNamespace(content=responses.pop(0)),
            )])

        client.chat.completions.create = describe
        with patch.object(image_index_service.time, "sleep") as sleep:
            description = image_index_service._describe(client, "data:image/jpeg;base64,test", 5)
        self.assertEqual(description, "图中展示了三个处理步骤。")
        self.assertEqual(len(client.chat_requests), 2)
        self.assertEqual(client.chat_requests[0]["extra_body"], {"enable_thinking": False})
        self.assertEqual(client.chat_requests[0]["max_tokens"], 1536)
        sleep.assert_called_once()

    def test_text_and_images_share_one_faiss_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            client = FakeSiliconFlowClient()
            with patch.object(pdf_service, "DATA_ROOT", root), \
                    patch.object(index_service, "DATA_ROOT", root), \
                    patch.object(image_index_service, "_client", return_value=client), \
                    patch.object(index_service, "load_embeddings", return_value=FakeTextEmbeddings()), \
                    patch.dict(os.environ, {
                        "SILICONFLOW_VISION_MODEL": "Qwen/Qwen3.6-35B-A3B",
                        "SILICONFLOW_EMBEDDING_MODEL": "Qwen/Qwen3-VL-Embedding-8B",
                    }):
                file_id = "test-pdf"
                path = pdf_service.images_dir(file_id) / "page2_img1.png"
                Image.new("RGB", (60, 40), "red").save(path)
                index_service.markdown_path(file_id).write_text(
                    "# 第 2 页\n\n这里介绍系统架构。\n\n![Image](./images/page2_img1.png)\n",
                    encoding="utf-8",
                )
                legacy = root / file_id / "index_images"
                legacy.mkdir()
                (legacy / "old-index").write_text("stale")

                result = index_service.build_multimodal_index(file_id)
                self.assertEqual(result, {"ok": True, "chunks": 1, "images": 1})
                self.assertTrue((index_service.index_dir(file_id) / "index.faiss").exists())
                self.assertFalse(legacy.exists())

                hits = index_service.search_faiss(file_id, "流程图", k=2)
                self.assertTrue(hits["ok"])
                self.assertEqual([hit["kind"] for hit in hits["results"]], ["image", "text"])
                self.assertIn("page2_img1.png", hits["results"][0]["imageUrl"])
                self.assertEqual(hits["results"][0]["metadata"]["page"], 2)
                self.assertEqual(hits["results"][1]["metadata"]["page"], 2)
                self.assertEqual(client.chat_requests[0]["model"], "Qwen/Qwen3.6-35B-A3B")
                self.assertEqual(client.embedding_requests[0]["model"], "Qwen/Qwen3-VL-Embedding-8B")
                self.assertIn("image", client.embedding_requests[0]["input"])

                index_service.build_multimodal_index(file_id)
                self.assertEqual(len(client.chat_requests), 1, "unchanged image descriptions should be reused")
                cache = json.loads((pdf_service.workdir(file_id) / "image_descriptions.json").read_text())
                self.assertEqual(cache[path.name]["model"], "Qwen/Qwen3.6-35B-A3B")

                with patch.dict(os.environ, {"SILICONFLOW_EMBEDDING_MODEL": "another-model"}):
                    self.assertEqual(
                        index_service.search_faiss(file_id, "流程图")["error"],
                        "INDEX_REBUILD_REQUIRED",
                    )

    def test_image_only_markdown_can_build_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(pdf_service, "DATA_ROOT", root), \
                    patch.object(index_service, "DATA_ROOT", root), \
                    patch.object(image_index_service, "_client", return_value=FakeSiliconFlowClient()), \
                    patch.object(index_service, "load_embeddings", return_value=FakeTextEmbeddings()):
                file_id = "image-only"
                Image.new("RGB", (40, 30), "red").save(pdf_service.images_dir(file_id) / "page1_img1.png")
                index_service.markdown_path(file_id).write_text(
                    "# 第 1 页\n\n![Image](./images/page1_img1.png)\n", encoding="utf-8"
                )
                result = index_service.build_multimodal_index(file_id)
                self.assertEqual(result, {"ok": True, "chunks": 0, "images": 1})
                self.assertEqual(index_service.search_faiss(file_id, "流程图")["results"][0]["kind"], "image")


if __name__ == "__main__":
    unittest.main()
