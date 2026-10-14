# services/pdf_service.py
from __future__ import annotations
import io
from pathlib import Path
from typing import Dict, Any, List
import pymupdf
from PIL import Image
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

def extract_native_text_pages(file_id: str) -> List[List[Dict[str, Any]]]:
    """读取每页的原生文字与图片区域，保留扫描页供逐页 OCR。"""
    pages: List[List[Dict[str, Any]]] = []
    with pymupdf.open(original_pdf_path(file_id)) as doc:
        for page_number, page in enumerate(doc, start=1):
            blocks = []

            def add_block(category: str, bbox, content: str = "") -> None:
                x0, y0, x1, y1 = bbox
                blocks.append({
                    "text": content,
                    "metadata": {
                        "page_number": page_number,
                        "category": category,
                        "coordinates": {
                            "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                            "layout_width": page.rect.width,
                            "layout_height": page.rect.height,
                        },
                    },
                })

            for block in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, content, _, block_type = block
                content = content.strip()
                if block_type != 0 or not content:
                    continue
                add_block("Text", (x0, y0, x1, y1), content)
            # get_image_info 返回页面上实际绘制的图片位置，也能识别内联图片。
            for image in page.get_image_info():
                bbox = pymupdf.Rect(image["bbox"]) & page.rect
                if not bbox.is_empty:
                    add_block("Image", bbox)
            pages.append(blocks)
    return pages


def _ocr_text_blocks(page, page_number: int, tessdata: Path) -> List[Dict[str, Any]]:
    # 局部 OCR 保留已有文字层，并识别页面中的扫描图片。
    textpage = page.get_textpage_ocr(
        language="chi_sim+eng", dpi=200, full=False, tessdata=str(tessdata)
    )
    text_blocks = []
    for x0, y0, x1, y1, content, _, block_type in page.get_text(
        "blocks", sort=True, textpage=textpage
    ):
        content = content.strip()
        if block_type != 0 or not content:
            continue
        text_blocks.append({
            "text": content,
            "metadata": {
                "page_number": page_number,
                "category": "Text",
                "coordinates": {
                    "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    "layout_width": page.rect.width,
                    "layout_height": page.rect.height,
                },
            },
        })
    return text_blocks


def ocr_scanned_pages(file_id: str, pages: List[List[Dict[str, Any]]]) -> List[List[Dict[str, Any]]]:
    """仅对文字层不足且含图片的页面 OCR，保留其他页的原生文字。"""
    scan_pages = [
        page_number for page_number, blocks in enumerate(pages, start=1)
        if sum(
            len(block["text"].strip()) for block in blocks
            if block["metadata"]["category"] == "Text"
        ) < 20
        and any(block["metadata"]["category"] == "Image" for block in blocks)
    ]
    if not scan_pages:
        return pages

    try:
        tessdata = Path(pymupdf.get_tessdata())
    except RuntimeError as exc:
        raise RuntimeError("扫描页需要 Tesseract OCR 和中文语言包；macOS 可运行 brew install tesseract tesseract-lang") from exc
    missing = [lang for lang in ("chi_sim", "eng") if not (tessdata / f"{lang}.traineddata").is_file()]
    if missing:
        raise RuntimeError(f"扫描页缺少 Tesseract 语言包：{', '.join(missing)}")

    with pymupdf.open(original_pdf_path(file_id)) as doc:
        for page_number in scan_pages:
            page = doc.load_page(page_number - 1)
            text_blocks = _ocr_text_blocks(page, page_number, tessdata)
            image_blocks = [
                block for block in pages[page_number - 1]
                if block["metadata"]["category"] == "Image"
            ]
            pages[page_number - 1] = text_blocks + image_blocks
    return pages

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

def extract_embedded_images(file_id: str) -> Dict[int, List[str]]:
    pdf_path = str(original_pdf_path(file_id))
    img_dir = images_dir(file_id)
    image_map: Dict[int, List[str]] = {}
    with pymupdf.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            image_map[page_num] = []
            # Image blocks include inline images, which page.get_images() omits.
            image_blocks = (block for block in page.get_text("dict")["blocks"] if block["type"] == 1)
            for img_index, block in enumerate(image_blocks, start=1):
                img_path = img_dir / f"page{page_num}_img{img_index}.png"
                with Image.open(io.BytesIO(block["image"])) as image:
                    image.convert("RGB").save(img_path, format="PNG")
                image_map[page_num].append(img_path.name)
    return image_map

def native_pdf_to_markdown(file_id: str, pages: List[List[Dict[str, Any]]]) -> Dict[str, str]:
    """保留页码和文字顺序，供索引与引用使用。"""
    image_map = extract_embedded_images(file_id)
    md_lines: List[str] = []
    for page_number, blocks in enumerate(pages, start=1):
        md_lines.append(f"# 第 {page_number} 页")
        md_lines.extend(block["text"] for block in blocks if block["text"])
        md_lines.extend(f"![Image](./images/{name})" for name in image_map[page_number])
    out_md = markdown_output(file_id)
    out_md.write_text("\n\n".join(md_lines) + "\n", encoding="utf-8")
    return {"markdown": out_md.name, "images_dir": "images"}

def run_full_parse_pipeline(file_id: str) -> Dict[str, Any]:
    """
    完整流程：文字层优先直读；扫描件使用 OCR；随后渲染页图并输出 Markdown。
    返回用于 /status 的统计或元信息
    """
    pages = extract_native_text_pages(file_id)
    pages = ocr_scanned_pages(file_id, pages)
    render_original_pages(file_id)
    docs = [block for page in pages for block in page]
    render_parsed_pages_with_boxes(file_id, docs)
    md_info = native_pdf_to_markdown(file_id, pages)
    return {"md": md_info["markdown"]}
