import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class RestoreCurrentPdfTests(unittest.TestCase):
    def test_restores_parsed_pdf_after_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            folder = root / "f_12345678"
            (folder / "pages" / "original").mkdir(parents=True)
            (folder / "original.pdf").write_bytes(b"pdf")
            (folder / "output.md").write_text("# 第 1 页", encoding="utf-8")
            (folder / "pages" / "original" / "page-0001.png").write_bytes(b"png")
            state = {"fileId": None, "name": None, "pages": 0, "status": "idle", "progress": 0}
            with patch.object(app, "current_pdf", state), patch.object(app, "Path", return_value=root):
                self.assertFalse(app.restore_current_pdf("../other"))
                self.assertTrue(app.restore_current_pdf("f_12345678"))
                self.assertEqual(state["status"], "ready")
                self.assertEqual(state["pages"], 1)
                self.assertFalse(app.restore_current_pdf("f_87654321"))


if __name__ == "__main__":
    unittest.main()
