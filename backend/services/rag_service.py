# services/rag_service.py
from __future__ import annotations
import os, asyncio, re, textwrap
from typing import List, Dict, Any, Tuple, AsyncGenerator
from typing_extensions import TypedDict

from dotenv import load_dotenv
load_dotenv(override=True)

from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import FAISS
from collections import defaultdict
from pathlib import Path
from services.embedding_service import DEFAULT_BASE_URL, ensure_index_compatible, load_embeddings

# 存储结构：sessions[session_id] = [{"role":"user|assistant","content":"..."}...]
_sessions: dict[str, list[dict]] = defaultdict(list)

def get_history(session_id: str) -> list[dict]:
    return _sessions.get(session_id, [])

def append_history(session_id: str, role: str, content: str) -> None:
    _sessions[session_id].append({"role": role, "content": content})

def clear_history(session_id: str) -> None:
    _sessions.pop(session_id, None)

# ---------------- 配置 ----------------
MODEL_NAME = "deepseek-chat"
MODEL_PROVIDER = "deepseek"
TEMPERATURE = 0
GRADER_MODEL = "Qwen/Qwen3.8-27B"

K = 3

SYSTEM_INSTRUCTION = (
    "你是多模态 PDF 检索 RAG 助手，可以围绕用户上传的文档进行解析、检索和问答。\n"
    "请优先使用当前上传并已解析/索引的文档来回答问题；若未检索到相关内容，则基于通识知识作答，"
    "并**明确说明未找到匹配的文档片段**。\n"
    "当检索到的上下文中包含与答案直接相关的图片时，请在回答中一并给出这些图片的 Markdown 引用，"
    "例如：`![参考图1](图片URL)`。如果没有合适的图片，也就是如果没有检索到图片，或者用户只是让你介绍自己的功能，勿强行添加图片路径。绝不伪造图片或路径。"
)

GRADE_PROMPT = (
    "你是一个判定器，评估检索到的上下文是否有助于回答用户问题。\n"
    "上下文片段：\n{context}\n\n问题：{question}\n"
    "如果上下文对回答该问题有帮助，只返回 yes；否则只返回 no。不要解释。"
)

ANSWER_WITH_CONTEXT = (
    "请使用提供的上下文回答用户的问题。\n\n"
    "问题：\n{question}\n\n上下文：\n{context}\n\n"
    "要求：使用 Markdown；表达简洁但完整；如需给出代码，请使用三引号代码块（```）。\n"
    "若上下文包含与答案直接相关的图片，请在相关段落后内联给出 1–3 张图片（Markdown 语法），"
    "作为一名助人为乐的助手，你需要仔细详细的感受用户的需求，并作出详细的回答。如果有图片，请在回答中给出图片的Markdown引用。"
)

ANSWER_NO_CONTEXT = (
    "当前未找到与上传文档直接相关的片段，将基于通识知识作答。\n"
    "问题：\n{question}"
)


# ---------------- 模型/向量函数 ----------------
def _get_llm():
    return init_chat_model(model=MODEL_NAME, model_provider=MODEL_PROVIDER, temperature=TEMPERATURE)

def _get_grader():
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 SILICONFLOW_API_KEY，请在 backend/.env 中配置硅基流动 API Key")
    return ChatOpenAI(
        model=os.getenv("SILICONFLOW_GRADER_MODEL", GRADER_MODEL),
        api_key=api_key,
        base_url=os.getenv("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL),
        temperature=0,
    )

def _vs_dir(file_id: str) -> str:
    return os.path.join("data", file_id, "index_faiss")

def _load_vs(file_id: str) -> FAISS:
    vs_path = _vs_dir(file_id)
    idx_file = os.path.join(vs_path, "index.faiss")
    if not os.path.exists(idx_file):
        raise FileNotFoundError(f"FAISS index not found at {vs_path}; build index first.")
    ensure_index_compatible(Path(vs_path))
    return FAISS.load_local(vs_path, load_embeddings(), allow_dangerous_deserialization=True)

# ---------------- 主流程：检索 + 判定 + 生成 ----------------
async def retrieve(question: str, file_id: str) -> tuple[list[dict], str]:
    """
    返回 (citations, context_text)
    citations: [{citation_id, fileId, rank, page, snippet, score, previewUrl}]
    context_text: 供 LLM 使用的拼接上下文
    """
    vs = _load_vs(file_id)
    hits = vs.similarity_search_with_score(question, k=K)
    citations = []
    ctx_snippets = []
    for i, (doc, score) in enumerate(hits, start=1):
        snippet_short = (doc.page_content or "").strip()
        if len(snippet_short) > 500:
            snippet_short = snippet_short[:500] + "..."
        page = doc.metadata.get("page") or doc.metadata.get("page_number")
        citations.append({
            "citation_id": f"{file_id}-c{i}",
            "fileId": file_id,
            "rank": i,
            "page": page,
            "snippet": (doc.page_content or "")[:4000],
            "score": float(score),
            "previewUrl": f"/api/v1/pdf/page?fileId={file_id}&page={(page or 1)}&type=original",
        })
        ctx_snippets.append(f"[{i}] {snippet_short}")
    if not ctx_snippets:
        return [], ""
    context_text = "\n\n".join(ctx_snippets)

    grader = _get_grader()
    grade_prompt = GRADE_PROMPT.format(context=context_text, question=question)
    decision = await grader.ainvoke([{"role": "user", "content": grade_prompt}])
    relevant = bool(re.match(r"^yes\b", (decision.content or "").strip(), re.IGNORECASE))
    return citations, context_text if relevant else ""

async def answer_stream(
    question: str,
    citations: list[dict],
    context_text: str,
    branch: str,
    session_id: str | None = None
) -> AsyncGenerator[dict, None]:
    """
    以增量事件的形式产出：
      {"type":"citation", "data": {...}}
      {"type":"token", "data": "text chunk"}
      {"type":"done", "data": {"used_retrieval": bool}}
    同时：如果提供了 session_id，会把本轮问答写入内存历史。
    """
    # 先把 citations 全部发给前端（便于角标立刻出现）
    if branch == "with_context" and citations:
        for c in citations:
            yield {"type": "citation", "data": c}

    # 组装“历史 + 本轮提示”
    llm = _get_llm()
    history_msgs = get_history(session_id) if session_id else []

    if branch == "with_context" and context_text:
        user_prompt = ANSWER_WITH_CONTEXT.format(question=question, context=context_text)
    else:
        user_prompt = ANSWER_NO_CONTEXT.format(question=question)

    # 完整消息序列：system + 历史多轮 + 当前用户
    msgs = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
    # 将历史逐条附加（保持 role: "user"/"assistant"）
    msgs.extend(history_msgs)
    # 当前用户问题
    msgs.append({"role": "user", "content": user_prompt})

    # 把最终生成的文本拼接出来用于写历史
    final_text_parts: list[str] = []

    # 优先使用流式
    try:
        async for chunk in llm.astream(msgs):
            delta = getattr(chunk, "content", None)
            if delta:
                final_text_parts.append(delta)
                yield {"type": "token", "data": delta}
    except Exception:
        # 回退：非流式整段生成
        resp = await llm.ainvoke(msgs)
        text = resp.content or ""
        final_text_parts.append(text)
        for i in range(0, len(text), 20):
            yield {"type": "token", "data": text[i:i+20]}
            await asyncio.sleep(0.005)

    if branch == "with_context" and citations:
        imgs = []
        # 取前 2 张，避免过多（可按需改成 3）
        for c in citations[:2]:
            url = c.get("previewUrl")
            if url:
                # 生成 Markdown 图片行
                imgs.append(f"![参考页 {c.get('rank', '')}]({url})")
        if imgs:
            tail = "\n\n---\n**相关页面预览**\n\n" + "\n\n".join(imgs)
            # 作为一个额外 token 块发给前端
            yield {"type": "token", "data": tail}

    # 将本轮问答写入历史（仅在提供 session_id 时）
    if session_id:
        append_history(session_id, "user", question)
        append_history(session_id, "assistant", "".join(final_text_parts))

    yield {"type": "done", "data": {"used_retrieval": branch == "with_context"}}
