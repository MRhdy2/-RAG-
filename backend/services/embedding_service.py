"""SiliconFlow embeddings shared by indexing and retrieval."""

import json
import os
from pathlib import Path

from langchain_openai import OpenAIEmbeddings


DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
METADATA_FILENAME = "embedding.json"


class IndexRebuildRequiredError(ValueError):
    """The FAISS index was built with an unknown or different embedding model."""


def embedding_model() -> str:
    return os.getenv("SILICONFLOW_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def load_embeddings() -> OpenAIEmbeddings:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 SILICONFLOW_API_KEY，请在 backend/.env 中配置硅基流动 API Key")

    # SiliconFlow implements the OpenAI-compatible embeddings endpoint. This
    # client uses only the SiliconFlow URL and key; OPENAI_API_KEY is ignored.
    return OpenAIEmbeddings(
        api_key=api_key,
        base_url=os.getenv("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL),
        model=embedding_model(),
        check_embedding_ctx_length=False,
        encoding_format="float",
    )


def save_index_metadata(index_path: Path) -> None:
    metadata = {"provider": "siliconflow", "model": embedding_model()}
    (index_path / METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )


def ensure_index_compatible(index_path: Path) -> None:
    metadata_path = index_path / METADATA_FILENAME
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raise IndexRebuildRequiredError("索引缺少 Embedding 模型信息，请重新构建索引") from None

    if not isinstance(metadata, dict) or metadata.get("provider") != "siliconflow" or metadata.get("model") != embedding_model():
        raise IndexRebuildRequiredError("索引使用了不同的 Embedding 模型，请重新构建索引")
