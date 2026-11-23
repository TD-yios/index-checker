from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@unittest.skipUnless(os.environ.get("IC_UI_SMOKE") == "1", "set IC_UI_SMOKE=1 to run UI smoke")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["LOCALAPPDATA"] = cls.tmp.name
        os.environ["APPDATA"] = cls.tmp.name
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_main_window_and_dialogs(self) -> None:
        from app import MainWindow
        from ui_dialogs import AboutDialog, BrandRenameDialog, QueryConfigDialog
        from ui_shared import APP_VERSION

        window = MainWindow()
        self.assertIn(f"v{APP_VERSION}", window.windowTitle())
        self.assertTrue(window.logger.path.name.startswith("run_"))

        about = AboutDialog(window)
        self.assertLessEqual(about.sizeHint().width(), 620)
        query = QueryConfigDialog(window.query_settings, 2, 1, window)
        self.assertEqual(set(query.proxy_buttons), {"baidu", "google", "bing", "toutiao"})
        brand = BrandRenameDialog(window.library, "测试品牌", 2, window)
        self.assertIsNotNone(brand.new_edit)
        window.library.close()
        window.close()


if __name__ == "__main__":
    unittest.main()
