# services/pdf_service.py
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
from typing import Dict, Any, List
import pymupdf
from PIL import Image
from dotenv import load_dotenv
import matplotlib
matplotlib.use("Agg")  # 服务器无头
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# 统一的根目录：每个 fileId 一个子目录
DATA_ROOT = Path("data")

def workdir(file_id: str) -> Path:
    d = DATA_ROOT / file_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def dir_original_pages(file_id: str) -> Path:
    p = workdir(file_id) / "pages" / "original"
    p.mkdir(parents=True, exist_ok=True); return p

def dir_parsed_pages(file_id: str) -> Path:
    p = workdir(file_id) / "pages" / "parsed"
    p.mkdir(parents=True, exist_ok=True); return p

def original_pdf_path(file_id: str) -> Path:
    return workdir(file_id) / "original.pdf"

def markdown_output(file_id: str) -> Path:
    return workdir(file_id) / "output.md"

def images_dir(file_id: str) -> Path:
    p = workdir(file_id) / "images"
    p.mkdir(parents=True, exist_ok=True); return p

def save_upload(file_id: str, upload_bytes: bytes, filename: str) -> Dict[str, Any]:
    """保存上传的 PDF，并返回页数"""
    pdf_path = original_pdf_path(file_id)
    pdf_path.write_bytes(upload_bytes)
    with pymupdf.open(pdf_path) as doc:
        pages = doc.page_count
    return {"fileId": file_id, "name": filename, "pages": pages}

def render_original_pages(file_id: str, dpi: int = 144):
    """把原始 PDF 渲染为 PNG，存到 pages/original/"""
    pdf_path = original_pdf_path(file_id)
    out_dir = dir_original_pages(file_id)
    with pymupdf.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            mat = pymupdf.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            (out_dir / f"page-{idx:04d}.png").write_bytes(pix.tobytes("png"))

def content_list_path(file_id: str) -> Path:
    return workdir(file_id) / "content_list.json"


def image_pages_path(file_id: str) -> Path:
    return workdir(file_id) / "image_pages.json"


def _content_page(item: Dict[str, Any], page_count: int) -> int | None:
    page_idx = item.get("page_idx")
    if isinstance(page_idx, int) and 0 <= page_idx < page_count:
        return page_idx + 1
    return None


def _save_mineru_result(file_id: str, result, page_count: int) -> List[Dict[str, Any]]:
    if result.state != "done" or not result.markdown or not result.markdown.strip():
        raise RuntimeError(f"MinerU 精细解析未返回 Markdown：{result.error or result.state}")
    names = [image.name for image in result.images]
    if len(names) != len(set(names)):
        raise RuntimeError("MinerU 返回了重名图片，无法安全保存")

    result.save_markdown(str(markdown_output(file_id)), with_images=True)
    content = result.content_list or []
    if not isinstance(content, list):
        raise RuntimeError("MinerU 返回的内容列表格式无效")
    content_list_path(file_id).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")

    image_pages: Dict[str, int] = {}
    segments: List[Dict[str, Any]] = []
    with pymupdf.open(original_pdf_path(file_id)) as doc:
        for item in content:
            if not isinstance(item, dict):
                continue
            page_number = _content_page(item, page_count)
            if page_number is None:
                continue
            image_path = item.get("img_path") or item.get("image_path")
            if isinstance(image_path, str):
                image_pages[PurePosixPath(image_path).name] = page_number

            bbox = item.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                x0, y0, x1, y1 = (float(value) for value in bbox)
            except (TypeError, ValueError):
                continue
            page = doc[page_number - 1]
            x0, x1 = x0 * page.rect.width / 1000, x1 * page.rect.width / 1000
            y0, y1 = y0 * page.rect.height / 1000, y1 * page.rect.height / 1000
            if x1 <= x0 or y1 <= y0:
                continue
            kind = item.get("type")
            category = "Image" if kind in ("image", "chart") else "Table" if kind == "table" else "Text"
            segments.append({"metadata": {
                "page_number": page_number,
                "category": category,
                "coordinates": {
                    "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    "layout_width": page.rect.width,
                    "layout_height": page.rect.height,
                },
            }})
    image_pages_path(file_id).write_text(json.dumps(image_pages, ensure_ascii=False), encoding="utf-8")
    return segments

def _plot_boxes_to_ax(ax, pix, segments):
    category_to_color = {
        "Title": "orchid",
        "Image": "limegreen",
        "Table": "tomato",
    }
    categories = set()
    for seg in segments:
        points = seg["coordinates"]["points"]
        lw = seg["coordinates"]["layout_width"]
        lh = seg["coordinates"]["layout_height"]
        scaled = [(x * pix.width / lw, y * pix.height / lh) for x, y in points]
        color = category_to_color.get(seg.get("category"), "deepskyblue")
        categories.add(seg.get("category", "Text"))
        poly = patches.Polygon(scaled, linewidth=2 if seg.get("category") == "Image" else 1,
                               edgecolor=color, facecolor="none")
        ax.add_patch(poly)

    legend_handles = [patches.Patch(color="deepskyblue", label="Text")]
    for cat, color in category_to_color.items():
        if cat in categories:
            legend_handles.append(patches.Patch(color=color, label=cat))
    ax.legend(handles=legend_handles, loc="lower right", bbox_to_anchor=(1, 1.01),
              ncol=len(legend_handles), fontsize=8, borderaxespad=0)

def render_parsed_pages_with_boxes(file_id: str, docs_local: List[Dict[str, Any]], dpi: int = 144):
    """
    根据解析段的 metadata（含坐标）在原图上叠框，输出到 pages/parsed/
    """
    pdf_path = original_pdf_path(file_id)
    out_dir = dir_parsed_pages(file_id)
    with pymupdf.open(pdf_path) as doc:
        # 预聚合：按 page_number 分组 segments
        segments_by_page: Dict[int, List[Dict[str, Any]]] = {}
        for d in docs_local:
            meta = d.metadata if hasattr(d, "metadata") else d["metadata"]
            pno = meta.get("page_number")
            if pno is None: continue
            segments_by_page.setdefault(pno, []).append(meta)

        for page_number in range(1, doc.page_count + 1):
            page = doc.load_page(page_number - 1)
            mat = pymupdf.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=mat)
            pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            fig, ax = plt.subplots(1, figsize=(10, 10))
            ax.imshow(pil)
            ax.axis("off")
            _plot_boxes_to_ax(ax, pix, segments_by_page.get(page_number, []))
            fig.tight_layout()
            fig.savefig(out_dir / f"page-{page_number:04d}.png", bbox_inches="tight", pad_inches=0)
            plt.close(fig)

def run_full_parse_pipeline(file_id: str) -> Dict[str, Any]:
    """使用 MinerU 精细解析生成 Markdown 与图片，PyMuPDF 仅用于预览渲染。"""
    from mineru import MinerU

    load_dotenv(override=True)
    token = os.getenv("MINERU_TOKEN") or os.getenv("MINERU_API_KEY")
    if not token:
        raise RuntimeError("缺少 MINERU_TOKEN，请在 backend/.env 中配置 MinerU API Token")

    with pymupdf.open(original_pdf_path(file_id)) as doc:
        page_count = doc.page_count
    with MinerU(token) as client:
        result = client.extract(
            str(original_pdf_path(file_id)), model="vlm", ocr=True,
            formula=True, table=True, language="ch", timeout=1800,
        )
    segments = _save_mineru_result(file_id, result, page_count)
    render_original_pages(file_id)
    render_parsed_pages_with_boxes(file_id, segments)
    return {"md": markdown_output(file_id).name}
