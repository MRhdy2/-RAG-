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
                    pdf_service, "unstructured_segments", side_effect=AssertionError("OCR should not run")
                ):
                    pdf_service.run_full_parse_pipeline(file_id)

                markdown = pdf_service.markdown_output(file_id).read_text(encoding="utf-8")
                chunks = split_markdown(markdown)
                self.assertEqual({chunk.metadata.get("page") for chunk in chunks}, {1, 2})
                self.assertEqual(len(list(pdf_service.dir_original_pages(file_id).glob("*.png"))), 2)
                self.assertEqual(len(list(pdf_service.dir_parsed_pages(file_id).glob("*.png"))), 2)
                self.assertEqual(len(list(pdf_service.images_dir(file_id).glob("*.png"))), 1)


if __name__ == "__main__":
    unittest.main()
