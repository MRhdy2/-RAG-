# services/index_service.py
from __future__ import annotations
import re
from pathlib import Path
from typing import List, Dict, Any
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from services.embedding_service import (
    IndexRebuildRequiredError, ensure_index_compatible, load_embeddings,
    save_index_metadata,
)

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
        txt = (d.page_content or "").strip()
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
        cleaned.append(Document(page_content=txt, metadata=metadata))
    return cleaned

def build_faiss_index(file_id: str) -> Dict[str, Any]:
    md_file = markdown_path(file_id)
    if not md_file.exists():
        return {"ok": False, "error": "MARKDOWN_NOT_FOUND"}
    md_text = md_file.read_text(encoding="utf-8")

    docs = split_markdown(md_text)
    if not docs:
        return {"ok": False, "error": "EMPTY_MD"}

    embeddings = load_embeddings()
    vs = FAISS.from_documents(docs, embedding=embeddings)
    idx = index_dir(file_id)
    vs.save_local(str(idx))
    save_index_metadata(idx)
    return {"ok": True, "chunks": len(docs)}

def search_faiss(file_id: str, query: str, k: int = 5) -> Dict[str, Any]:
    idx = index_dir(file_id)
    if not (idx / "index.faiss").exists():
        return {"ok": False, "error": "INDEX_NOT_FOUND"}

    try:
        ensure_index_compatible(idx)
    except IndexRebuildRequiredError:
        return {"ok": False, "error": "INDEX_REBUILD_REQUIRED"}

    embeddings = load_embeddings()
    vs = FAISS.load_local(str(idx), embeddings, allow_dangerous_deserialization=True)
    hits = vs.similarity_search_with_score(query, k=k)
    results = []
    for doc, score in hits:
        results.append({
            "text": doc.page_content,
            "score": float(score),
            "metadata": doc.metadata,
        })
    return {"ok": True, "results": results}
