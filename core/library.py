from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .config import normalize_domain


def library_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "IndexChecker"
    p.mkdir(parents=True, exist_ok=True)
    return p


def normalize_target_url(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        raise ValueError("目标 URL 为空")
    if "://" not in s:
        s = "https://" + s
    parts = urlsplit(s)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("只支持 http / https 网址")
    host = (parts.hostname or "").strip(".").lower()
    if not host or "." not in host:
        raise ValueError("网址缺少有效域名")
    if any(ch.isspace() for ch in host):
        raise ValueError("域名中不能有空格")
    netloc = parts.netloc
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, parts.fragment))


class KeywordLibrary:
    """本地关键词库：品牌 + 关键词 + 目标 URL + 最近查询状态。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else library_data_dir() / "library.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                keyword TEXT NOT NULL,
                target_url TEXT NOT NULL,
                target_domain TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_query_at TEXT DEFAULT '',
                last_status TEXT DEFAULT 'pending',
                last_summary TEXT DEFAULT '',
                last_engine TEXT DEFAULT '',
                UNIQUE(brand, keyword)
            );
            CREATE INDEX IF NOT EXISTS idx_keywords_brand ON keywords(brand);
            CREATE INDEX IF NOT EXISTS idx_keywords_status ON keywords(last_status);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM keywords ORDER BY brand COLLATE NOCASE, keyword COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0])

    def get(self, record_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM keywords WHERE id=?", (int(record_id),)).fetchone()
        return dict(row) if row else None

    def add(self, brand: str, keyword: str, target_url: str) -> dict[str, Any]:
        brand = (brand or "").strip()
        keyword = (keyword or "").strip()
        if not brand:
            raise ValueError("品牌不能为空")
        if not keyword:
            raise ValueError("关键词不能为空")
        url = normalize_target_url(target_url)
        domain = normalize_domain(url)
        duplicate = self.conn.execute(
            "SELECT id FROM keywords WHERE lower(brand)=lower(?) AND lower(keyword)=lower(?)",
            (brand, keyword),
        ).fetchone()
        if duplicate:
            raise ValueError("同品牌下已存在这个关键词")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            cur = self.conn.execute(
                "INSERT INTO keywords(brand, keyword, target_url, target_domain, created_at) "
                "VALUES(?,?,?,?,?)",
                (brand, keyword, url, domain, now),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("同品牌下已存在这个关键词") from exc
        record = self.get(int(cur.lastrowid))
        assert record is not None
        return record

    def add_many(self, entries: Iterable[dict[str, Any]]) -> int:
        added = 0
        for item in entries:
            try:
                self.add(item.get("brand", ""), item.get("keyword", ""), item.get("target_url", ""))
                added += 1
            except Exception:
                continue
        return added

    def update_url(self, record_id: int, target_url: str) -> None:
        url = normalize_target_url(target_url)
        domain = normalize_domain(url)
        self.conn.execute(
            "UPDATE keywords SET target_url=?, target_domain=? WHERE id=?",
            (url, domain, int(record_id)),
        )
        self.conn.commit()

    def update_record(self, record_id: int, brand: str, keyword: str, target_url: str) -> None:
        """完整编辑一条关键词记录，品牌、关键词、目标 URL 都可改。"""
        brand = (brand or "").strip()
        keyword = (keyword or "").strip()
        if not brand:
            raise ValueError("品牌不能为空")
        if not keyword:
            raise ValueError("关键词不能为空")
        url = normalize_target_url(target_url)
        domain = normalize_domain(url)
        duplicate = self.conn.execute(
            "SELECT id FROM keywords "
            "WHERE lower(brand)=lower(?) AND lower(keyword)=lower(?) AND id<>?",
            (brand, keyword, int(record_id)),
        ).fetchone()
        if duplicate:
            raise ValueError("同品牌下已存在这个关键词")
        try:
            self.conn.execute(
                "UPDATE keywords SET brand=?, keyword=?, target_url=?, target_domain=? WHERE id=?",
                (brand, keyword, url, domain, int(record_id)),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("同品牌下已存在这个关键词") from exc

    def rename_brand(self, old_brand: str, new_brand: str, merge: bool = False) -> tuple[int, int]:
        """重命名品牌；目标品牌已存在时可选择合并。

        返回 (移动的关键词数, 合并时删除的重复关键词数)。merge=False 时，
        如果目标品牌下已有同名关键词会抛 ValueError，避免静默丢数据。
        """
        old_brand = (old_brand or "").strip()
        new_brand = (new_brand or "").strip()
        if not old_brand:
            raise ValueError("原品牌为空")
        if not new_brand:
            raise ValueError("新品牌不能为空")
        if old_brand == new_brand:
            return 0, 0
        rows = self.conn.execute(
            "SELECT * FROM keywords WHERE brand=?", (old_brand,)
        ).fetchall()
        if not rows:
            raise ValueError("原品牌下没有关键词")
        conflicts = self.conn.execute(
            "SELECT keyword FROM keywords WHERE lower(brand)=lower(?) "
            "AND lower(keyword) IN ("
            "SELECT lower(keyword) FROM keywords WHERE brand=?"
            ")",
            (new_brand, old_brand),
        ).fetchall()
        if conflicts and not merge:
            names = "、".join(str(r["keyword"]) for r in conflicts[:5])
            more = " 等" if len(conflicts) > 5 else ""
            raise ValueError(f"目标品牌下已有同名关键词：{names}{more}，请选择合并")

        moved = 0
        merged = 0
        try:
            with self.conn:
                for row in rows:
                    duplicate = self.conn.execute(
                        "SELECT id FROM keywords WHERE lower(brand)=lower(?) "
                        "AND lower(keyword)=lower(?) AND id<>?",
                        (new_brand, row["keyword"], int(row["id"])),
                    ).fetchone()
                    if duplicate:
                        if not merge:
                            raise ValueError("目标品牌下已有同名关键词")
                        self.conn.execute("DELETE FROM keywords WHERE id=?", (int(row["id"]),))
                        merged += 1
                        continue
                    self.conn.execute(
                        "UPDATE keywords SET brand=? WHERE id=?",
                        (new_brand, int(row["id"])),
                    )
                    moved += 1
        except sqlite3.IntegrityError as exc:
            raise ValueError("品牌重命名失败：目标品牌存在重复关键词") from exc
        return moved, merged

    def delete(self, record_ids: Iterable[int]) -> int:
        ids = [int(x) for x in record_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM keywords WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids)

    def mark_status(self, record_ids: Iterable[int], status: str) -> None:
        ids = [int(x) for x in record_ids]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(
            f"UPDATE keywords SET last_status=? WHERE id IN ({placeholders})",
            [status, *ids],
        )
        self.conn.commit()

    def reset_stale_running(self) -> int:
        """上次进程异常退出时，库里的“查询中”会永久卡住；启动时恢复为待查。"""
        cur = self.conn.execute(
            "UPDATE keywords SET last_status='pending', last_summary='上次查询未完成' "
            "WHERE last_status='running'"
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def record_result(self, record_id: int | None, status: str, summary: str, engine: str) -> None:
        if not record_id:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE keywords SET last_query_at=?, last_status=?, last_summary=?, last_engine=? WHERE id=?",
            (now, status, summary, engine, int(record_id)),
        )
        self.conn.commit()

    def seed_from_last_config(self, config_path: Path | None = None) -> int:
        if self.count() > 0:
            return 0
        path = Path(config_path) if config_path else Path(os.environ.get("APPDATA") or str(Path.home())) / "IndexChecker" / "last_config.json"
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        keywords = [str(x).strip() for x in (data.get("keywords") or []) if str(x).strip()]
        domain = str(data.get("target_domain") or "").strip()
        if not keywords or not domain:
            return 0
        brand = keywords[0]
        url = "https://" + domain
        added = 0
        for kw in keywords:
            try:
                self.add(brand, kw, url)
                added += 1
            except Exception:
                continue
        return added

    def parse_import_rows(self, rows: Iterable[Iterable[Any]]) -> list[dict[str, str]]:
        existing = {(r["brand"].lower(), r["keyword"].lower()) for r in self.all()}
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, str]] = []
        for raw in rows:
            cells = [str(x).strip() if x is not None else "" for x in raw]
            if not any(cells):
                continue
            brand = cells[0] if len(cells) > 0 else ""
            keyword = cells[1] if len(cells) > 1 else ""
            url = cells[2] if len(cells) > 2 else ""
            if brand.lower() in ("品牌", "brand") and keyword.lower() in ("关键词", "keyword"):
                continue
            item = {"brand": brand, "keyword": keyword, "target_url": url}
            if not brand or not keyword or not url:
                result.append({**item, "check": "invalid", "message": "三列都要填写"})
                continue
            try:
                normalized = normalize_target_url(url)
            except Exception as exc:
                result.append({**item, "check": "invalid", "message": str(exc)})
                continue
            item["target_url"] = normalized
            key = (brand.lower(), keyword.lower())
            if key in existing or key in seen:
                result.append({**item, "check": "duplicate", "message": "重复，导入时跳过"})
                continue
            seen.add(key)
            result.append({**item, "check": "valid", "message": "可导入"})
        return result

    def parse_import_text(self, text: str) -> list[dict[str, str]]:
        import csv
        rows: list[list[str]] = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "\t" in line and "," not in line:
                rows.append([x.strip() for x in line.split("\t")])
            else:
                rows.append([x.strip() for x in next(csv.reader([line], skipinitialspace=True))])
        return self.parse_import_rows(rows)

    def import_valid(self, checked_rows: Iterable[dict[str, str]]) -> int:
        entries = [r for r in checked_rows if r.get("check") == "valid"]
        return self.add_many(entries)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
