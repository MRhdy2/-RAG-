import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image

from services import pdf_service
from services.index_service import split_markdown


class PdfServiceTests(unittest.TestCase):
    def test_text_pdf_parses_without_ocr_and_keeps_page_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(pdf_service, "DATA_ROOT", Path(temp_dir)):
                file_id = "text-pdf"
                with pymupdf.open() as document:
                    for page_number in (1, 2):
                        page = document.new_page()
                        page.insert_text(
                            (72, 72),
                            f"This is searchable text on page {page_number} of the PDF document.",
                        )
                        if page_number == 1:
                            image_bytes = io.BytesIO()
                            Image.new("RGB", (50, 30), "red").save(image_bytes, format="PNG")
                            page.insert_image(pymupdf.Rect(72, 120, 172, 200),
                                              stream=image_bytes.getvalue(), keep_proportion=False)
                    document.save(pdf_service.original_pdf_path(file_id))

                native_pages = pdf_service.extract_native_text_pages(file_id)
                self.assertIsNotNone(native_pages)
                images = [block for block in native_pages[0]
                          if block["metadata"]["category"] == "Image"]
                self.assertEqual(len(images), 1)
                self.assertEqual(len([block for block in native_pages[1]
                                      if block["metadata"]["category"] == "Image"]), 0)
                self.assertAlmostEqual(images[0]["metadata"]["coordinates"]["points"][0][0], 72)

                with patch.object(
                    pdf_service.pymupdf, "get_tessdata", side_effect=AssertionError("OCR should not run")
                ):
                    pdf_service.run_full_parse_pipeline(file_id)

                markdown = pdf_service.markdown_output(file_id).read_text(encoding="utf-8")
                chunks = split_markdown(markdown)
                self.assertEqual({chunk.metadata.get("page") for chunk in chunks}, {1, 2})
                self.assertEqual(len(list(pdf_service.dir_original_pages(file_id).glob("*.png"))), 2)
                self.assertEqual(len(list(pdf_service.dir_parsed_pages(file_id).glob("*.png"))), 2)
                self.assertEqual(len(list(pdf_service.images_dir(file_id).glob("*.png"))), 1)

    def test_mixed_pdf_only_ocrs_scanned_page_and_keeps_both_page_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(pdf_service, "DATA_ROOT", Path(temp_dir)):
                file_id = "mixed-pdf"
                with pymupdf.open() as document:
                    document.new_page().insert_text(
                        (72, 72), "Native text remains searchable on the first page."
                    )
                    page = document.new_page()
                    image_bytes = io.BytesIO()
                    Image.new("RGB", (200, 80), "white").save(image_bytes, format="PNG")
                    page.insert_image(pymupdf.Rect(72, 72, 472, 232), stream=image_bytes.getvalue())
                    document.save(pdf_service.original_pdf_path(file_id))

                tessdata = Path(temp_dir) / "tessdata"
                tessdata.mkdir()
                for language in ("chi_sim", "eng"):
                    (tessdata / f"{language}.traineddata").touch()

                def fake_ocr(page, page_number, _tessdata):
                    self.assertEqual(page_number, 2)
                    self.assertEqual(_tessdata, tessdata)
                    return [{
                        "text": "Scanned page text",
                        "metadata": {
                            "page_number": page_number,
                            "category": "Text",
                            "coordinates": {
                                "points": [(72, 72), (472, 72), (472, 232), (72, 232)],
                                "layout_width": page.rect.width,
                                "layout_height": page.rect.height,
                            },
                        },
                    }]

                with patch.object(pdf_service.pymupdf, "get_tessdata", return_value=str(tessdata)), \
                     patch.object(pdf_service, "_ocr_text_blocks", side_effect=fake_ocr) as ocr:
                    pdf_service.run_full_parse_pipeline(file_id)

                ocr.assert_called_once()
                markdown = pdf_service.markdown_output(file_id).read_text(encoding="utf-8")
                self.assertIn("# 第 1 页", markdown)
                self.assertIn("Native text remains searchable", markdown)
                self.assertIn("# 第 2 页", markdown)
                self.assertIn("Scanned page text", markdown)
                chunks = split_markdown(markdown)
                self.assertEqual({chunk.metadata.get("page") for chunk in chunks}, {1, 2})


if __name__ == "__main__":
    unittest.main()
