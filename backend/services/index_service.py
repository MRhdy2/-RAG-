# services/index_service.py
from __future__ import annotations
import re
import shutil
from pathlib import Path
from typing import List, Dict, Any
from urllib.parse import urlencode
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from services.embedding_service import (
    IndexRebuildRequiredError, ensure_index_compatible, load_embeddings,
    save_index_metadata,
)
from services.image_index_service import prepare_image_embeddings, vision_model

from dotenv import load_dotenv
load_dotenv(override=True)

# 复用你已有的数据目录结构
DATA_ROOT = Path("data")

def workdir(file_id: str) -> Path:
    p = DATA_ROOT / file_id
    p.mkdir(parents=True, exist_ok=True)
    return p

def markdown_path(file_id: str) -> Path:
    return workdir(file_id) / "output.md"

def index_dir(file_id: str) -> Path:
    p = workdir(file_id) / "index_faiss"
    p.mkdir(parents=True, exist_ok=True)
    return p

def split_markdown(md_text: str) -> List[Document]:
    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        # 需要更细可以加 ("###", "Header 3")
    ]
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    docs = splitter.split_text(md_text)
    # 可加一点清洗
    cleaned: List[Document] = []
    for d in docs:
        txt = re.sub(r"!\[[^\]]*]\(\./images/[^)]+\)", "", d.page_content or "").strip()
        if not txt:
            continue
        # 限制太长的段落，避免向量化出错
        if len(txt) > 8000:
            txt = txt[:8000]
        metadata = dict(d.metadata)
        page_heading = metadata.get("Header 1", "")
        page_match = re.fullmatch(r"第\s*(\d+)\s*页", page_heading)
        if page_match:
            metadata["page"] = int(page_match.group(1))
        metadata["kind"] = "text"
        cleaned.append(Document(page_content=txt, metadata=metadata))
    return cleaned

def build_faiss_index(file_id: str) -> Dict[str, Any]:
    md_file = markdown_path(file_id)
    if not md_file.exists():
        return {"ok": False, "error": "MARKDOWN_NOT_FOUND"}
    md_text = md_file.read_text(encoding="utf-8")

    docs = split_markdown(md_text)
    image_items = prepare_image_embeddings(file_id)
    if not docs and not image_items:
        return {"ok": False, "error": "EMPTY_MD"}

    embeddings = load_embeddings()
    if docs:
        vs = FAISS.from_documents(docs, embedding=embeddings, normalize_L2=True)
        if image_items:
            vs.add_embeddings(
                [(description, vector) for description, vector, _ in image_items],
                metadatas=[metadata for _, _, metadata in image_items],
            )
    else:
        vs = FAISS.from_embeddings(
            [(description, vector) for description, vector, _ in image_items],
            embedding=embeddings,
            metadatas=[metadata for _, _, metadata in image_items],
            normalize_L2=True,
        )
    idx = index_dir(file_id)
    vs.save_local(str(idx))
    save_index_metadata(idx, vision_model())
    legacy_images = workdir(file_id) / "index_images"
    if legacy_images.is_dir():
        shutil.rmtree(legacy_images)
    return {"ok": True, "chunks": len(docs), "images": len(image_items)}


def build_multimodal_index(file_id: str) -> Dict[str, Any]:
    return build_faiss_index(file_id)

def search_faiss(file_id: str, query: str, k: int = 5) -> Dict[str, Any]:
    idx = index_dir(file_id)
    if not (idx / "index.faiss").exists():
        return {"ok": False, "error": "INDEX_NOT_FOUND"}

    try:
        ensure_index_compatible(idx, vision_model())
    except IndexRebuildRequiredError:
        return {"ok": False, "error": "INDEX_REBUILD_REQUIRED"}

    embeddings = load_embeddings()
    vs = FAISS.load_local(str(idx), embeddings, allow_dangerous_deserialization=True, normalize_L2=True)
    hits = vs.similarity_search_with_score(query, k=k)
    results = []
    for doc, score in hits:
        result = {
            "kind": doc.metadata.get("kind", "text"),
            "text": doc.page_content,
            "score": float(score),
            "metadata": doc.metadata,
        }
        if result["kind"] == "image":
            result["imageUrl"] = "/api/v1/pdf/images?" + urlencode({
                "fileId": file_id, "imagePath": doc.metadata["imagePath"],
            })
        results.append(result)
    return {"ok": True, "results": results}
