from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 打包后通过 --cli 复用同一入口执行查询引擎
if "--cli" in sys.argv:
    idx = sys.argv.index("--cli")
    sys.argv = [sys.argv[0]] + sys.argv[idx + 1:]
    from runner import main as runner_main
    raise SystemExit(runner_main())

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from core.config import ENGINE_LABEL, JobConfig
from core.library import KeywordLibrary
from ui_dialogs import AboutDialog, QueryConfigDialog
from ui_library import LibraryPage
from ui_pages import DashboardPage, ReportsPage
from ui_query import QueryPage
from ui_shared import (
    APP_VERSION, ENGINE_ORDER, RunLogger, RunnerThread, STYLE, SingleInstance,
    app_data_dir, browser_summary, default_outdir, link_button, load_query_settings,
    logs_dir, save_query_settings,
)

APP_NAME = "收录查询工具"


def resource_path(relative: str) -> Path:
    """源码运行时取项目目录，PyInstaller 运行时取 _MEIPASS。"""
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    return base / relative


def _merge_summaries(items: list[tuple[str, str]]) -> str:
    """多引擎时把同类命中数合并，避免“品牌 1 · 自然 3 · 品牌 1 · 自然 3”。"""
    counts: dict[str, int] = {}
    for _engine, text in items:
        for part in text.split(" · "):
            label, _, value = part.rpartition(" ")
            if value.isdigit():
                counts[label] = counts.get(label, 0) + int(value)
    order = ["品牌", "卡片", "广告", "自然"]
    labels = [x for x in order if x in counts] + [x for x in counts if x not in order]
    return " · ".join(f"{label} {counts[label]}" for label in labels if counts[label])


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("IndexChecker", "IndexChecker")
        self.query_settings = load_query_settings(self.settings)
        self.library = KeywordLibrary()
        self._migrate_library_once()
        self.library.reset_stale_running()
        self._report_dirs = self._load_report_dirs()
        self.logger = RunLogger()

        self.thread: RunnerThread | None = None
        self.stop_requested = False
        self.last_outdir = ""
        self.last_report = ""
        self._run_ids: list[int] = []
        self._run_stats: dict[int, dict] = {}
        self._fatal_message = ""
        self._saw_done = False

        self.setWindowTitle(f"{APP_NAME} · 多品牌关键词库 · v{APP_VERSION}")
        self.resize(1360, 860)
        self.setMinimumSize(1100, 680)
        self._build_ui()

    # ---------------- layout ----------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setObjectName("SideBar")
        side.setFixedWidth(214)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(16, 24, 16, 16)
        side_lay.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        mark = QLabel("收")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            "background:#F4A621;color:#FFFFFF;border-radius:10px;"
            "font-size:17px;font-weight:900;"
        )
        brand_row.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("收录查询")
        name.setObjectName("BrandName")
        brand_text.addWidget(name)
        sub = QLabel("INDEX CHECKER")
        sub.setObjectName("BrandSub")
        brand_text.addWidget(sub)
        brand_row.addLayout(brand_text, 1)
        side_lay.addLayout(brand_row)
        side_lay.addSpacing(28)

        section = QLabel("工作")
        section.setStyleSheet(
            "font-size:9px;font-weight:800;color:#B4770B;letter-spacing:1px;padding-left:6px;"
        )
        side_lay.addWidget(section)
        side_lay.addSpacing(6)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("dashboard", "工作台"),
            ("library", "关键词库"),
            ("query", "查询任务"),
            ("reports", "报告中心"),
        ]
        for key, label in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            side_lay.addWidget(btn)

        side_lay.addStretch(1)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#EEF1F5;")
        side_lay.addWidget(line)
        side_lay.addSpacing(10)
        self.side_run = QLabel("当前没有查询")
        self.side_run.setObjectName("Muted")
        self.side_run.setWordWrap(True)
        side_lay.addWidget(self.side_run)
        side_lay.addSpacing(5)
        side_browser = QLabel(browser_summary())
        side_browser.setObjectName("Muted")
        side_browser.setWordWrap(True)
        side_browser.setStyleSheet("font-size:9px;color:#98A2B3;background:transparent;")
        side_lay.addWidget(side_browser)
        side_lay.addSpacing(7)
        local = QLabel("本地运行 · 不上传关键词")
        local.setStyleSheet("font-size:9px;color:#B6BFCC;background:transparent;")
        side_lay.addWidget(local)
        side_lay.addSpacing(7)

        about_row = QHBoxLayout()
        about_row.setSpacing(6)
        about = link_button("关于")
        about.setObjectName("LinkButton")
        about.clicked.connect(self.open_about)
        about_row.addWidget(about)
        about_row.addStretch(1)
        version = QLabel(f"v{APP_VERSION}")
        version.setStyleSheet("font-size:9px;color:#B6BFCC;background:transparent;")
        about_row.addWidget(version)
        side_lay.addLayout(about_row)

        root.addWidget(side)
        self.stack = QStackedWidget()
        self.stack.setObjectName("MainStack")
        root.addWidget(self.stack, 1)

        self.library_page = LibraryPage(self)
        self.dashboard_page = DashboardPage(self)
        self.query_page = QueryPage(self)
        self.reports_page = ReportsPage(self)
        self.pages = {
            "dashboard": self.dashboard_page,
            "library": self.library_page,
            "query": self.query_page,
            "reports": self.reports_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self._setup_shortcuts()
        self.switch_page("library")

    def _setup_shortcuts(self) -> None:
        shortcuts = [
            ("Ctrl+N", self.library_page.open_add),
            ("Ctrl+I", self.library_page.open_import),
            ("Ctrl+F", self._focus_library_search),
            ("Ctrl+Enter", self.library_page._query_selected),
            ("F5", self._refresh_all),
            ("Ctrl+Q", self.close),
        ]
        self._shortcuts: list[QShortcut] = []
        for sequence, handler in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    def _focus_library_search(self) -> None:
        self.switch_page("library")
        self.library_page.search.setFocus()
        self.library_page.search.selectAll()

    def _refresh_all(self) -> None:
        self.library_page.refresh()
        self.dashboard_page.refresh()
        self.reports_page.refresh()

    def switch_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        btn = self.nav_buttons.get(key)
        if btn:
            btn.setChecked(True)
        if key == "dashboard":
            self.dashboard_page.refresh()
        elif key == "library":
            self.library_page.refresh()
            self.library_page.update_mode_label()
        elif key == "reports":
            self.reports_page.refresh()

    def open_about(self) -> None:
        AboutDialog(self).exec()

    # ---------------- cross-page API ----------------
    def _migrate_library_once(self) -> None:
        """只迁入一次旧 last_config；用户主动清空关键词后不会被再次写回。"""
        if self.library.get_meta("last_config_migrated") == "1":
            return
        if self.library.count() == 0:
            self.library.seed_from_last_config()
        self.library.set_meta("last_config_migrated", "1")

    def _load_report_dirs(self) -> list[str]:
        path = app_data_dir() / "reports.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except Exception:
            pass
        return []

    def _remember_report_dir(self, folder: str) -> None:
        if not folder:
            return
        try:
            normalized = str(Path(folder).resolve())
        except Exception:
            return
        items = [normalized] + [x for x in self._report_dirs if x != normalized]
        self._report_dirs = items[:200]
        try:
            (app_data_dir() / "reports.json").write_text(
                json.dumps(self._report_dirs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def is_running(self) -> bool:
        return bool(self.thread and self.thread.isRunning())

    def query_defaults(self) -> dict:
        return self.query_settings

    def after_library_change(self) -> None:
        self.library_page.refresh()
        self.library_page.update_mode_label()
        self.dashboard_page.refresh()

    def outdir_base(self) -> Path:
        raw = str(self.query_settings.get("outdir") or "").strip()
        return Path(raw).expanduser() if raw else default_outdir()

    def report_entries(self) -> list[dict]:
        base = self.outdir_base()
        candidates: list[Path] = []
        if base.exists():
            candidates.append(base)
            candidates.extend(sorted((p for p in base.iterdir() if p.is_dir()),
                                    key=lambda p: p.name, reverse=True))
        candidates.extend(Path(x) for x in self._report_dirs)
        entries = []
        seen: set[str] = set()
        for folder in candidates:
            if not folder.is_dir():
                continue
            key = str(folder.resolve())
            if key in seen:
                continue
            xlsx = folder / "收录查询报告.xlsx"
            csv = folder / "查询汇总.csv"
            report = xlsx if xlsx.exists() else (csv if csv.exists() else None)
            if not report:
                continue
            seen.add(key)
            try:
                stat = report.stat()
            except OSError:
                continue
            entries.append({
                "dir": folder,
                "report": report,
                "mtime": datetime.fromtimestamp(stat.st_mtime),
                "size": stat.st_size,
            })
        return sorted(entries, key=lambda x: (x["mtime"], x["dir"].name), reverse=True)

    # ---------------- query orchestration ----------------
    def start_records(self, records: list[dict]) -> None:
        if not records:
            return
        if self.is_running():
            QMessageBox.information(self, "查询进行中", "上一轮查询还没结束，请先等待或停止。")
            return
        brands = {str(r.get("brand") or "") for r in records}
        dlg = QueryConfigDialog(self.query_settings, len(records), len(brands), self)
        if dlg.exec() != QDialog.Accepted:
            return
        values = dlg.values()
        self.query_settings = values
        save_query_settings(self.settings, values)

        enabled = [n for n in ENGINE_ORDER if values["engines"].get(n)]
        if not enabled:
            QMessageBox.warning(self, "请选择引擎", "至少选择一个搜索引擎。")
            return

        tasks = []
        for r in records:
            tasks.append({
                "brand": str(r.get("brand") or ""),
                "keyword": str(r.get("keyword") or ""),
                "target_url": str(r.get("target_url") or ""),
                "library_id": int(r["id"]),
            })
        ids = [int(r["id"]) for r in records]

        base = Path(values["outdir"]).expanduser()
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(self, "输出目录不可用", str(exc))
            return
        run_dir = base / datetime.now().strftime("%Y%m%d_%H%M%S")
        if run_dir.exists():
            run_dir = base / f"{run_dir.name}_{datetime.now().strftime('%f')[:3]}"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(self, "输出目录不可用", str(exc))
            return

        engines = {
            n: {
                "enabled": bool(values["engines"].get(n)),
                "proxy": str((values.get("proxies") or {}).get(n) or ""),
            }
            for n in ENGINE_ORDER
        }
        cfg = JobConfig(
            tasks=tasks,
            engines=engines,
            max_pages=int(values.get("pages") or 2),
            stop_on_hit=bool(values.get("stop_on_hit", True)),
            screenshot_all_pages=bool(values.get("screenshot_all", False)),
            headless=bool(values.get("headless", True)),
            delay_min=float(values.get("delay") or 2.0),
            delay_max=float(values.get("delay") or 2.0),
            output_dir=str(run_dir),
        )
        errs = cfg.validate()
        if errs:
            QMessageBox.warning(self, "查询设置", "\n".join(errs))
            return

        config_path = app_data_dir() / "run_config.json"
        payload = asdict(cfg)
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self._run_ids = ids
        self._run_stats = {}
        self._fatal_message = ""
        self._saw_done = False
        self.stop_requested = False
        self.last_outdir = str(run_dir)
        self.last_report = ""
        self.logger.write({
            "type": "ui_start",
            "task_count": len(records),
            "brand_count": len(brands),
            "engines": enabled,
            "outdir": str(run_dir),
        })
        self.library.mark_status(ids, "running")
        self.library_page.refresh()
        self.dashboard_page.refresh()

        self.query_page.reset_run(
            total_tasks=len(records) * len(enabled),
            keyword_count=len(records),
            brand_count=len(brands),
            engines=enabled,
            run_dir=str(run_dir),
        )
        self.side_run.setText(f"查询中 · {len(records)} 个关键词")
        self.switch_page("query")

        self.thread = RunnerThread(config_path, app_data_dir() / "stop.flag", self)
        self.thread.event.connect(self._on_runner_event)
        self.thread.finished_code.connect(self._on_runner_finished)
        self.thread.start()

    def stop_query(self) -> None:
        if not self.is_running():
            return
        self.stop_requested = True
        self.side_run.setText("正在停止…")
        if self.thread:
            self.thread.request_stop()
        QTimer.singleShot(3500, self._force_terminate)

    def _force_terminate(self) -> None:
        if self.thread and self.thread.proc and self.thread.proc.poll() is None:
            self.thread.kill_tree()

    def _on_runner_event(self, ev: dict) -> None:
        self.logger.write(ev)
        etype = ev.get("type")
        if etype == "task_done":
            rid = ev.get("library_id")
            if rid:
                st = self._run_stats.setdefault(int(rid), {"statuses": [], "summaries": [], "engines": []})
                st["statuses"].append(str(ev.get("status") or ""))
                st["summaries"].append((str(ev.get("engine_label") or ""), str(ev.get("summary") or "")))
                st["engines"].append(str(ev.get("engine_label") or ""))
        elif etype == "done":
            self._saw_done = True
            self.last_outdir = str(ev.get("outdir") or self.last_outdir)
            self.last_report = str(ev.get("xlsx") or ev.get("csv") or "")
            self._remember_report_dir(self.last_outdir)
        elif etype == "fatal":
            self._fatal_message = str(ev.get("message") or "查询失败")
        self.query_page.handle_event(ev)

    def _on_runner_finished(self, code: int) -> None:
        if self.thread:
            self.thread.wait(1500)
        self.thread = None

        for rid in self._run_ids:
            st = self._run_stats.get(rid)
            if st and st["statuses"]:
                statuses = st["statuses"]
                if "hit" in statuses:
                    status = "hit"
                elif "error" in statuses:
                    status = "error"
                elif "miss" in statuses:
                    status = "miss"
                else:
                    status = "pending"
                parts = [summary for _eng, summary in st["summaries"] if summary]
                summary = _merge_summaries(st["summaries"]) or " · ".join(parts) or "0 命中"
                engines = " / ".join(dict.fromkeys(e for e in st["engines"] if e))
            elif self._fatal_message:
                status = "error"
                summary = self._fatal_message
                engines = ""
            elif self.stop_requested:
                status = "pending"
                summary = "已停止"
                engines = ""
            else:
                status = "pending"
                summary = "未执行"
                engines = ""
            self.library.record_result(rid, status, summary, engines)

        if not self._saw_done:
            if self.stop_requested or self.query_page._stopping:
                self.query_page.handle_event({"type": "stopped", "message": "查询已停止"})
            else:
                self.query_page.handle_event({
                    "type": "fatal",
                    "message": self._fatal_message or f"查询进程未返回完成事件（{code}）",
                })
        stop_requested = self.stop_requested
        self.stop_requested = False
        self.side_run.setText("当前没有查询")
        self.logger.write({
            "type": "ui_finished",
            "exit_code": code,
            "saw_done": self._saw_done,
            "stopped": stop_requested,
        })
        self.library_page.refresh()
        self.dashboard_page.refresh()
        self.reports_page.refresh()

    def closeEvent(self, event) -> None:
        if self.is_running():
            answer = QMessageBox.question(
                self, "退出工具", "查询还在进行，确定停止并退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            if self.thread:
                self.thread.request_stop()
                if not self.thread.wait(3000):
                    self.thread.kill_tree()
                    if not self.thread.wait(5000):
                        QMessageBox.warning(
                            self, "无法退出",
                            "查询进程仍在运行，请稍后再试；如持续出现，请在任务管理器结束 IndexChecker。",
                        )
                        event.ignore()
                        return
        self.library.close()
        event.accept()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = QIcon(str(resource_path("assets/app.ico")))
    if not icon.isNull():
        app.setWindowIcon(icon)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    instance = SingleInstance()
    if instance.activate_existing():
        return 0
    win = MainWindow()
    if not instance.listen(win):
        QMessageBox.warning(
            None, "无法启动",
            "检测到收录查询工具可能已在运行，但无法唤起已有窗口。请先关闭任务管理器中的 IndexChecker 再试。",
        )
        return 2
    win._instance = instance
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
