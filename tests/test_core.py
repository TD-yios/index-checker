from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.library import KeywordLibrary, normalize_target_url
from core.proxy import normalize_proxy
from core.engines import (
    ResultItem, calc_global_rank, decode_wrapped_url, get_engine, judge_hit,
)


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.library = KeywordLibrary(Path(self.tmp.name) / "library.db")

    def tearDown(self) -> None:
        self.library.close()
        self.tmp.cleanup()

    def test_add_and_unique(self) -> None:
        row = self.library.add("示例品牌", "北京装修", "example.com")
        self.assertEqual(row["target_domain"], "example.com")
        with self.assertRaises(ValueError):
            self.library.add("示例品牌", "北京装修", "https://other.example")
        with self.assertRaises(ValueError):
            self.library.add("示例品牌", "北京装修 ", "https://other.example")

    def test_update_record(self) -> None:
        row = self.library.add("品牌A", "关键词A", "https://a.example")
        self.library.update_record(row["id"], "品牌B", "关键词B", "https://b.example/x")
        updated = self.library.get(row["id"])
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated["brand"], "品牌B")
        self.assertEqual(updated["keyword"], "关键词B")
        self.assertEqual(updated["target_domain"], "b.example")

    def test_rename_brand_keeps_records(self) -> None:
        self.library.add("旧品牌", "词1", "https://a.example")
        self.library.add("旧品牌", "词2", "https://b.example")
        moved, merged = self.library.rename_brand("旧品牌", "新品牌")
        self.assertEqual((moved, merged), (2, 0))
        self.assertEqual({r["brand"] for r in self.library.all()}, {"新品牌"})

    def test_merge_brand_reports_conflicts(self) -> None:
        self.library.add("旧品牌", "词1", "https://old.example")
        self.library.add("旧品牌", "词2", "https://old.example/2")
        self.library.add("目标品牌", "词1", "https://target.example")
        with self.assertRaises(ValueError):
            self.library.rename_brand("旧品牌", "目标品牌")
        moved, merged = self.library.rename_brand("旧品牌", "目标品牌", merge=True)
        self.assertEqual((moved, merged), (1, 1))
        rows = [(r["brand"], r["keyword"]) for r in self.library.all()]
        self.assertIn(("目标品牌", "词1"), rows)
        self.assertIn(("目标品牌", "词2"), rows)

    def test_import_validation(self) -> None:
        parsed = self.library.parse_import_text(
            "品牌,关键词,目标URL\n示例品牌,装修,https://www.example.com\n"
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["check"], "valid")


class EngineTests(unittest.TestCase):
    def test_global_rank_page1_pos1(self) -> None:
        self.assertEqual(calc_global_rank(1, 1, 10), 1)

    def test_global_rank_page2_pos2(self) -> None:
        self.assertEqual(calc_global_rank(2, 2, 10), 12)

    def test_global_rank_page3_pos5(self) -> None:
        self.assertEqual(calc_global_rank(3, 5, 10), 25)

    def test_global_rank_custom_per_page(self) -> None:
        self.assertEqual(calc_global_rank(2, 3, 20), 23)

    def test_global_rank_invalid_input(self) -> None:
        with self.assertRaises(ValueError):
            calc_global_rank(0, 1, 10)

    def test_global_rank_actual_previous_count(self) -> None:
        self.assertEqual(calc_global_rank(2, 1, 10, previous_organic=9), 10)
        self.assertEqual(calc_global_rank(2, 2, 10, previous_organic=9), 11)
        with self.assertRaises(ValueError):
            calc_global_rank(2, 1, 10, previous_organic=-1)

    def test_google_display_fallback_records_visible_domain(self) -> None:
        item = ResultItem(
            rank=1,
            title="示例品牌",
            href="https://www.google.com.hk/goto?url=encrypted",
            display="www.example.com",
        )
        matched, url = judge_hit(item, "example.com", "google")
        self.assertTrue(matched)
        self.assertEqual(url, "https://www.example.com")

    def test_toutiao_nested_jump_is_unwrapped(self) -> None:
        href = (
            "https://sou.toutiao.com/search/jump?url=https%3A%2F%2Fsou.toutiao.com"
            "%2Fsearch%2Fjump%3Furl%3Dhttp%253A%252F%252Fwww.example.com%252F"
            "%26aid%3D4916%26jtoken%3D&aid=4916&jtoken="
        )
        self.assertEqual(
            decode_wrapped_url(href, "toutiao"),
            "http://www.example.com/",
        )
        item = ResultItem(rank=1, title="示例品牌", href=href, display="示例品牌")
        matched, url = judge_hit(item, "example.com", "toutiao")
        self.assertTrue(matched)
        self.assertEqual(url, "http://www.example.com/")

    def test_toutiao_engine_is_registered(self) -> None:
        engine = get_engine("toutiao")
        self.assertEqual(engine.name, "toutiao")
        self.assertIn("so.toutiao.com", engine.build_url("示例品牌", 1, 10))


class ProxyTests(unittest.TestCase):
    def test_normalize_proxy(self) -> None:
        self.assertEqual(normalize_proxy("127.0.0.1:7890"), "http://127.0.0.1:7890")
        self.assertEqual(normalize_proxy("http://127.0.0.1:7890/"), "http://127.0.0.1:7890")
        with self.assertRaises(ValueError):
            normalize_proxy("socks5://127.0.0.1:1080")
        with self.assertRaises(ValueError):
            normalize_proxy("")

    def test_normalize_target_url(self) -> None:
        self.assertEqual(normalize_target_url("example.com"), "https://example.com/")
        with self.assertRaises(ValueError):
            normalize_target_url("ftp://example.com")


class ReportTests(unittest.TestCase):
    def test_global_rank_columns_are_written(self) -> None:
        from core.report import HIT_COLS, SUMMARY_COLS, write_reports

        self.assertIn("页内位次", HIT_COLS)
        self.assertIn("全局排名", HIT_COLS)
        self.assertIn("自然首现全局位", SUMMARY_COLS)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = [{
                "时间": "2026-01-01", "品牌": "品牌", "关键词": "词",
                "目标URL": "https://example.com", "搜索引擎": "百度", "是否命中": "是",
                "自然首现页": 2, "自然首现页内位": 2, "自然首现全局位": 12,
            }]
            hit = [{
                "时间": "2026-01-01", "品牌": "品牌", "关键词": "词",
                "目标URL": "https://example.com", "搜索引擎": "百度", "页码": 2,
                "页内位次": 2, "全局排名": 12, "类型": "自然结果",
                "标题": "标题", "URL": "https://example.com", "截图": "",
            }]
            write_reports(out, summary, [], hit, {"目标域名": "example.com"})
            text = (out / "查询汇总.csv").read_text(encoding="utf-8-sig")
            self.assertIn("自然首现全局位", text)
            hit_text = (out / "命中明细.csv").read_text(encoding="utf-8-sig")
            self.assertIn("页内位次", hit_text)
            self.assertIn("全局排名", hit_text)


if __name__ == "__main__":
    unittest.main()
