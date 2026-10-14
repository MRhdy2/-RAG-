from fastapi import FastAPI, UploadFile, File, Query, Body
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio, time, os, random, string, json, re
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

from fastapi import BackgroundTasks
from services.pdf_service import (
    save_upload, run_full_parse_pipeline,
    original_pdf_path, dir_original_pages, dir_parsed_pages, markdown_output
)
from services.index_service import build_multimodal_index, search_faiss
from starlette.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse, JSONResponse
from services.rag_service import retrieve, answer_stream, clear_history

app = FastAPI(
    title="多模态 RAG 系统 API",
    version="1.0.0",
    description="PDF 解析、向量检索与问答服务。"
)

# 允许前端本地联调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 本地联调；生产环境需配置具体来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"

# ---------------- 内存态存储 ----------------
current_pdf: Dict[str, Any] = {
    "fileId": None,
    "name": None,
    "pages": 0,
    "status": "idle",      # idle | parsing | ready | error
    "progress": 0
}
citations: Dict[str, Dict[str, Any]] = {}   # citationId -> { fileId, page, snippet, bbox, previewUrl }

# ---------------- 工具函数 ----------------
def rid(prefix: str) -> str:
    return f"{prefix}_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

def now_ts() -> int:
    return int(time.time())

def err(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}, "requestId": rid("req"), "ts": now_ts()}


def restore_current_pdf(file_id: str) -> bool:
    """Recover a parsed local PDF after a development server reload."""
    if current_pdf["fileId"] == file_id:
        return True
    if current_pdf["fileId"] is not None or not re.fullmatch(r"f_[a-z0-9]{8}", file_id):
        return False
    folder = Path("data") / file_id
    if not (folder / "original.pdf").is_file() or not (folder / "output.md").is_file():
        return False
    pages = len(list((folder / "pages" / "original").glob("page-*.png")))
    if pages == 0:
        return False
    current_pdf.update({
        "fileId": file_id,
        "name": "original.pdf",
        "pages": pages,
        "status": "ready",
        "progress": 100,
        "errorMsg": None,
    })
    return True

# ---------------- Pydantic 模型（契约） ----------------
class ChatRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None
    pdfFileId: Optional[str] = None

# ---------------- Health ----------------
@app.get(f"{API_PREFIX}/health", tags=["Health"])
async def health():
    return {"ok": True, "version": "1.0.0"}

# ---------------- Chat（SSE，POST 返回 event-stream） ----------------
class ChatRequest(BaseModel):
    message: str
    sessionId: Optional[str] = None
    pdfFileId: Optional[str] = None

@app.post(f"{API_PREFIX}/chat", tags=["Chat"])
async def chat_stream(req: ChatRequest):
    """
    SSE 事件：token | citation | done | error
    """
    async def gen():
        try:
            question = (req.message or "").strip()
            session_id = (req.sessionId or "default").strip()  # 默认单会话
            file_id = (req.pdfFileId or "").strip()

            citations, context_text = [], ""
            branch = "no_context"
            if file_id:
                try:
                    citations, context_text = await retrieve(question, file_id)
                    branch = "with_context" if context_text else "no_context"
                except FileNotFoundError:
                    branch = "no_context"

            # 再推送 token 流（内部会写入历史）
            async for evt in answer_stream(
                question=question,
                citations=citations,
                context_text=context_text,
                branch=branch,
                session_id=session_id
            ):
                event_type = evt["type"]
                if event_type in ("token", "citation", "done"):
                    payload = {"text": evt["data"]} if event_type == "token" else evt["data"]
                    yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    headers = {"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)

# ---------------- Chat: 清除对话 ----------------
class ClearChatRequest(BaseModel):
    sessionId: Optional[str] = None

@app.post(f"{API_PREFIX}/chat/clear", tags=["Chat"])
async def chat_clear(req: ClearChatRequest):
    sid = (req.sessionId or "default").strip()
    clear_history(sid)
    return {"ok": True, "sessionId": sid, "cleared": True}


# ---------------- PDF: 上传（仅单文件，直接替换） ----------------

current_pdf = {"fileId": None, "name": None, "pages": 0, "status": "idle", "progress": 0, "errorMsg": None}

@app.post(f"{API_PREFIX}/pdf/upload", tags=["PDF"])
async def pdf_upload(file: UploadFile = File(...), replace: Optional[bool] = True):
    if not file:
        return JSONResponse(err("NO_FILE", "缺少文件"), status_code=400)
    # 生成新的 fileId（替换策略：上传即替换）
    fid = rid("f")
    saved = save_upload(fid, await file.read(), file.filename)
    current_pdf.update({**saved, "status": "idle", "progress": 0, "errorMsg": None})
    citations.clear()
    return saved

# ---------------- PDF: 触发解析 ----------------
@app.post(f"{API_PREFIX}/pdf/parse", tags=["PDF"])
async def pdf_parse(payload: Dict[str, Any] = Body(...), bg: BackgroundTasks = None):
    file_id = payload.get("fileId")
    if not current_pdf["fileId"] or current_pdf["fileId"] != file_id:
        return JSONResponse(err("FILE_NOT_FOUND", "未找到该文件"), status_code=400)

    current_pdf["status"] = "parsing"
    current_pdf["progress"] = 5
    current_pdf["errorMsg"] = None

    def _job():
        try:
            # 20 → 60 → 100 三阶段进度示意
            current_pdf["progress"] = 20
            run_full_parse_pipeline(file_id)   # 真解析
            current_pdf["progress"] = 100
            current_pdf["status"] = "ready"
        except Exception as e:
            current_pdf["status"] = "error"
            current_pdf["progress"] = 0
            current_pdf["errorMsg"] = f"PDF 解析失败：{e}"
            print("Parse error:", e)

    if bg is not None:
        bg.add_task(_job)
    else:
        _job()

    return {"jobId": rid("j")}

# ---------------- PDF: 状态 ----------------
@app.get(f"{API_PREFIX}/pdf/status", tags=["PDF"])
async def pdf_status(fileId: str = Query(...)):
    if not restore_current_pdf(fileId):
        return {"status": "idle", "progress": 0}
    resp = {"status": current_pdf["status"], "progress": current_pdf["progress"]}
    if current_pdf["status"] == "error":
        resp["errorMsg"] = current_pdf.get("errorMsg") or "解析失败"
    return resp

# ---------------- PDF: 页面图 ----------------
@app.get(f"{API_PREFIX}/pdf/page", tags=["PDF"])
async def pdf_page(
    fileId: str = Query(...),
    page: int = Query(..., ge=1),
    type: str = Query(..., pattern="^(original|parsed)$")
):
    if not restore_current_pdf(fileId):
        return JSONResponse(status_code=404, content=None)

    if current_pdf["status"] != "ready" and type == "parsed":
        # 未解析就请求 parsed 页，按你的契约可以给 400/403；这里保持 204 更温和
        return JSONResponse(status_code=204, content=None)

    base = dir_original_pages(fileId) if type == "original" else dir_parsed_pages(fileId)
    img = base / f"page-{page:04d}.png"
    if not img.exists():
        return JSONResponse(err("PAGE_NOT_FOUND", "页面不存在或未渲染"), status_code=404)
    return FileResponse(str(img), media_type="image/png")

# ---------------- PDF: 图片文件 ----------------
@app.get(f"{API_PREFIX}/pdf/images", tags=["PDF"])
async def pdf_images(
    fileId: str = Query(...),
    imagePath: str = Query(...)
):
    """获取PDF解析后的图片文件"""
    if not restore_current_pdf(fileId):
        return JSONResponse(status_code=404, content=None)

    # 构建图片文件的完整路径
    from services.pdf_service import images_dir
    image_file = images_dir(fileId) / imagePath

    if not image_file.exists():
        return JSONResponse(err("IMAGE_NOT_FOUND", "图片文件不存在"), status_code=404)

    # 检查文件是否在images目录内（安全考虑）
    try:
        image_file.resolve().relative_to(images_dir(fileId).resolve())
    except ValueError:
        return JSONResponse(err("INVALID_PATH", "无效的图片路径"), status_code=400)

    return FileResponse(str(image_file), media_type="image/png")

# ---------------- PDF: 引用片段 ----------------
@app.get(f"{API_PREFIX}/pdf/chunk", tags=["PDF"])
async def pdf_chunk(citationId: str = Query(...)):
    ref = citations.get(citationId)
    if not ref:
        return JSONResponse(err("NOT_FOUND", "无该引用"), status_code=404)
    return ref

class BuildIndexRequest(BaseModel):
    fileId: str

class SearchRequest(BaseModel):
    fileId: str
    query: str
    k: Optional[int] = 5

@app.post(f"{API_PREFIX}/index/build", tags=["Index"])
async def index_build(req: BuildIndexRequest):
    # 可校验：current_pdf["status"] 应为 ready
    if not restore_current_pdf(req.fileId):
        raise HTTPException(status_code=400, detail="FILE_NOT_FOUND_OR_NOT_CURRENT")
    if current_pdf["status"] != "ready":
        raise HTTPException(status_code=409, detail="NEED_PARSE_FIRST")

    try:
        out = await run_in_threadpool(build_multimodal_index, req.fileId)
    except Exception as exc:
        return JSONResponse(
            err("INDEX_BUILD_ERROR", f"索引构建失败：{str(exc)[:500]}"), status_code=502
        )
    if not out.get("ok"):
        return JSONResponse(err(out.get("error", "INDEX_BUILD_ERROR"), "索引构建失败"), status_code=500)
    return {"ok": True, "chunks": out["chunks"], "images": out["images"]}

@app.post(f"{API_PREFIX}/index/search", tags=["Index"])
async def index_search(req: SearchRequest):
    out = await run_in_threadpool(search_faiss, req.fileId, req.query, req.k or 5)
    if not out.get("ok"):
        code = out.get("error", "INDEX_NOT_FOUND")
        message = "Embedding 模型已变更，请重新构建索引" if code == "INDEX_REBUILD_REQUIRED" else "请先构建索引"
        return JSONResponse(err(code, message), status_code=400)
    return out
