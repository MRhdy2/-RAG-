import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from mineru import ExtractResult, Image as MinerUImage
from PIL import Image

from services import image_index_service, pdf_service
from services.index_service import split_mineru_content


class PdfServiceTests(unittest.TestCase):
    def test_mineru_precision_result_preserves_markdown_images_and_page_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(pdf_service, "DATA_ROOT", Path(temp_dir)):
                file_id = "mineru-pdf"
                with pymupdf.open() as document:
                    document.new_page()
                    document.new_page()
                    document.save(pdf_service.original_pdf_path(file_id))

                image_data = io.BytesIO()
                Image.new("RGB", (40, 30), "red").save(image_data, format="JPEG")
                markdown = "# Overview\n\nMinerU text\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n![chart](images/figure.jpg)\n"
                content = [
                    {"type": "text", "page_idx": 0, "text": "MinerU text", "bbox": [100, 100, 800, 200]},
                    {"type": "table", "page_idx": 1, "table_body": "<table><tr><td>1</td></tr></table>",
                     "bbox": [100, 200, 900, 400]},
                    {"type": "image", "page_idx": 1, "img_path": "images/figure.jpg",
                     "bbox": [100, 450, 900, 850]},
                ]
                result = ExtractResult(
                    task_id="task-1", state="done", markdown=markdown, content_list=content,
                    images=[MinerUImage(name="figure.jpg", path="images/figure.jpg", data=image_data.getvalue())],
                )
                with patch.object(pdf_service, "load_dotenv"), \
                     patch.dict(pdf_service.os.environ, {"MINERU_TOKEN": "test-token"}), \
                     patch("mineru.MinerU") as client_type:
                    client_type.return_value.__enter__.return_value.extract.return_value = result
                    self.assertEqual(pdf_service.run_full_parse_pipeline(file_id), {"md": "output.md"})

                client_type.assert_called_once_with("test-token")
                kwargs = client_type.return_value.__enter__.return_value.extract.call_args.kwargs
                self.assertEqual(kwargs["model"], "vlm")
                self.assertTrue(kwargs["ocr"])
                self.assertTrue(kwargs["formula"])
                self.assertTrue(kwargs["table"])
                self.assertEqual(pdf_service.markdown_output(file_id).read_text(encoding="utf-8"), markdown)
                self.assertEqual((pdf_service.images_dir(file_id) / "figure.jpg").read_bytes(), image_data.getvalue())
                self.assertEqual(json.loads(pdf_service.image_pages_path(file_id).read_text()), {"figure.jpg": 2})
                self.assertEqual(image_index_service._image_paths(file_id),
                                 [(2, pdf_service.images_dir(file_id) / "figure.jpg")])
                self.assertEqual({doc.metadata["page"] for doc in split_mineru_content(content)}, {1, 2})
                self.assertEqual(len(list(pdf_service.dir_original_pages(file_id).glob("*.png"))), 2)
                self.assertEqual(len(list(pdf_service.dir_parsed_pages(file_id).glob("*.png"))), 2)

    def test_missing_mineru_token_fails_before_placing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(pdf_service, "DATA_ROOT", Path(temp_dir)):
                file_id = "no-token"
                with pymupdf.open() as document:
                    document.new_page()
                    document.save(pdf_service.original_pdf_path(file_id))
                with patch.object(pdf_service, "load_dotenv"), \
                     patch.dict(pdf_service.os.environ, {"MINERU_TOKEN": "", "MINERU_API_KEY": ""}):
                    with self.assertRaisesRegex(RuntimeError, "MINERU_TOKEN"):
                        pdf_service.run_full_parse_pipeline(file_id)
                self.assertFalse(pdf_service.markdown_output(file_id).exists())


if __name__ == "__main__":
    unittest.main()
