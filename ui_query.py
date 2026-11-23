from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QPlainTextEdit,
)

from core.config import ENGINE_LABEL
from ui_shared import (
    TYPE_LABEL, TYPE_ORDER, danger_button, ghost_button, make_page_head,
    open_path, primary_button,
)


class QueryPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.page_events: list[dict[str, Any]] = []
        self.task_stats: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.report_path = ""
        self.total_tasks = 0
        self.done_tasks = 0
        self._stopping = False
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(12)

        self.stop_btn = danger_button("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.report_btn = ghost_button("打开报告")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._open_report)
        self.dir_btn = ghost_button("打开目录")
        self.dir_btn.setEnabled(False)
        self.dir_btn.clicked.connect(self._open_dir)
        self.head = make_page_head(
            "查询任务",
            "每个关键词按自己的目标 URL 查询；命中即停时可翻页查看自然排位，结束后自动回写关键词库。",
            "查询执行",
            [self.stop_btn, self.report_btn, self.dir_btn],
        )
        lay.addWidget(self.head)

        run_panel = QWidget()
        run_panel.setObjectName("Panel")
        run_panel.setAttribute(Qt.WA_StyledBackground, True)
        run_lay = QVBoxLayout(run_panel)
        run_lay.setContentsMargins(16, 12, 16, 12)
        run_lay.setSpacing(7)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.status = QLabel("准备查询")
        self.status.setObjectName("RunStatus")
        self.status.setStyleSheet("font-size:12px;font-weight:800;color:#8A5A05;")
        top.addWidget(self.status)
        self.run_label = QLabel("")
        self.run_label.setObjectName("Muted")
        top.addWidget(self.run_label)
        top.addStretch(1)
        self.count_label = QLabel("0 / 0")
        self.count_label.setObjectName("Muted")
        top.addWidget(self.count_label)
        run_lay.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(13)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        run_lay.addWidget(self.progress)
        self.summary = QLabel("等待查询结果。")
        self.summary.setObjectName("Muted")
        self.summary.setStyleSheet("font-size:10px;color:#8A94A6;")
        run_lay.addWidget(self.summary)
        lay.addWidget(run_panel)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        filter_title = QLabel("命中类型")
        filter_title.setObjectName("Muted")
        filter_row.addWidget(filter_title)
        self.type_checks: dict[str, QCheckBox] = {}
        for key, label in TYPE_ORDER:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(self._render_all)
            self.type_checks[key] = cb
            filter_row.addWidget(cb)
        filter_row.addSpacing(8)
        self.hit_summary = QLabel("命中 0 · 任务 0 · 页面 0")
        self.hit_summary.setObjectName("Muted")
        filter_row.addWidget(self.hit_summary)
        filter_row.addStretch(1)
        lay.addLayout(filter_row)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.results = QTableWidget(0, 9)
        self.results.setObjectName("ResultTable")
        self.results.setHorizontalHeaderLabels([
            "品牌", "关键词", "目标 URL", "引擎", "页", "状态", "命中", "命中类型 / 排位", "截图",
        ])
        self.results.verticalHeader().setVisible(False)
        self.results.setShowGrid(False)
        self.results.setSelectionMode(QAbstractItemView.NoSelection)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.setWordWrap(False)
        self.results.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.results.cellDoubleClicked.connect(self._open_cell)
        self._setup_table(self.results, [90, 150, 210, 82, 42, 90, 52, 300, 70])
        self.results.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabs.addTab(self.results, "查询结果")

        self.class_table = QTableWidget(0, 8)
        self.class_table.setObjectName("ResultTable")
        self.class_table.setHorizontalHeaderLabels([
            "品牌", "关键词", "引擎", "类型", "数量", "首现页", "首现位", "首现 URL",
        ])
        self.class_table.verticalHeader().setVisible(False)
        self.class_table.setShowGrid(False)
        self.class_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.class_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.class_table.setWordWrap(False)
        self._setup_table(self.class_table, [90, 150, 70, 100, 55, 70, 78, 500])
        self.class_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.tabs.addTab(self.class_table, "分类统计")

        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("查询日志会显示在这里…")
        self.tabs.addTab(self.log, "运行日志")
        lay.addWidget(self.tabs, 1)

    @staticmethod
    def _setup_table(table: QTableWidget, widths: list[int]) -> None:
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        for i, width in enumerate(widths):
            if i == 7 and table.columnCount() == 8:
                continue
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            table.setColumnWidth(i, width)
        table.setRowHeight(0, 44)

    def reset_run(self, total_tasks: int, keyword_count: int, brand_count: int,
                  engines: list[str], run_dir: str) -> None:
        self.total_tasks = max(1, total_tasks)
        self.page_events.clear()
        self.task_stats.clear()
        self.report_path = ""
        self.done_tasks = 0
        self._stopping = False
        self.results.setRowCount(0)
        self.class_table.setRowCount(0)
        self.log.clear()
        self.tabs.setCurrentWidget(self.results)
        self.progress.setRange(0, self.total_tasks)
        self.progress.setValue(0)
        self.count_label.setText(f"0 / {self.total_tasks}")
        self.status.setText("准备启动浏览器…")
        self.status.setStyleSheet("font-size:12px;font-weight:800;color:#8A5A05;")
        engine_text = " + ".join(ENGINE_LABEL[n] for n in engines)
        self.run_label.setText(f"{keyword_count} 个关键词 · {brand_count} 个品牌 · {engine_text}")
        self.summary.setText(f"输出目录：{run_dir}")
        self.hit_summary.setText("命中 0 · 任务 0 · 页面 0")
        self.stop_btn.setEnabled(True)
        self.report_btn.setEnabled(False)
        self.dir_btn.setEnabled(bool(run_dir))
        self._row_dir = run_dir

    def mark_stopping(self) -> None:
        self._stopping = True
        self.stop_btn.setEnabled(False)
        self.status.setText("正在停止…")
        self.status.setStyleSheet("font-size:12px;font-weight:800;color:#C24A45;")

    def handle_event(self, ev: dict[str, Any]) -> None:
        etype = ev.get("type")
        if etype == "start":
            if ev.get("total"):
                self.total_tasks = int(ev["total"])
                self.progress.setRange(0, self.total_tasks)
            self.summary.setText(f"输出目录：{ev.get('outdir', '')}")
            self._append_log("info", f"开始查询，任务 {ev.get('total', 0)} 个")
        elif etype == "log":
            self._append_log(ev.get("level", "info"), ev.get("message", ""))
        elif etype == "page":
            self.page_events.append(ev)
            self._update_task_stats(ev)
            self._render_all()
        elif etype == "task_done":
            self.done_tasks += 1
        elif etype == "progress":
            done = int(ev.get("done") or 0)
            total = int(ev.get("total") or self.total_tasks)
            self.total_tasks = max(1, total)
            self.progress.setRange(0, self.total_tasks)
            self.progress.setValue(min(done, self.total_tasks))
            self.count_label.setText(f"{done} / {self.total_tasks}")
        elif etype == "done":
            self.report_path = ev.get("xlsx", "") or ev.get("csv", "") or ""
            completed = min(self.done_tasks, self.progress.maximum())
            self.progress.setValue(completed)
            self.count_label.setText(f"{completed} / {self.progress.maximum()}")
            self.status.setText("已停止" if self._stopping else "查询完成")
            self.status.setStyleSheet(
                "font-size:12px;font-weight:800;color:%s;" % ("#C24A45" if self._stopping else "#1D8F66")
            )
            self.stop_btn.setEnabled(False)
            self.report_btn.setEnabled(bool(self.report_path))
            self.dir_btn.setEnabled(bool(ev.get("outdir")))
            self._row_dir = ev.get("outdir") or getattr(self, "_row_dir", "")
            summary = ev.get("summary") or {}
            self.summary.setText(
                f"完成 {summary.get('tasks', 0)} 个任务 · 命中任务 {summary.get('hit_tasks', 0)} · "
                f"命中记录 {summary.get('hits', 0)} · 检查页面 {summary.get('pages', 0)}"
            )
            self._append_log("ok", "查询结束，报告已生成" if self.report_path else "查询结束，未生成报告文件")
            self._render_all()
        elif etype == "stopped":
            self._stopping = True
            completed = min(self.done_tasks, self.progress.maximum())
            self.progress.setValue(completed)
            self.count_label.setText(f"{completed} / {self.progress.maximum()}")
            self.status.setText("已停止")
            self.status.setStyleSheet("font-size:12px;font-weight:800;color:#C24A45;")
            self.stop_btn.setEnabled(False)
            self._append_log("warn", ev.get("message", "已停止"))
        elif etype == "fatal":
            self.status.setText("启动失败")
            self.status.setStyleSheet("font-size:12px;font-weight:800;color:#C24A45;")
            self.stop_btn.setEnabled(False)
            self._append_log("error", ev.get("message", "未知错误"))
            self.summary.setText(ev.get("message", ""))

    def _append_log(self, level: str, message: str) -> None:
        if not message:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"error": "×", "warn": "!", "ok": "✓"}.get(level, "·")
        self.log.appendPlainText(f"{stamp}  {prefix}  {message}")

    def _update_task_stats(self, ev: dict[str, Any]) -> None:
        key = (ev.get("brand", ""), ev.get("keyword", ""), ev.get("engine", ""))
        st = self.task_stats.setdefault(key, {
            "brand": key[0], "keyword": key[1], "engine": ev.get("engine_label") or ENGINE_LABEL.get(key[2], key[2]),
            "pages": 0, "hits": 0, "types": {}, "first": {},
        })
        st["pages"] += 1
        for hit in ev.get("hits") or []:
            st["hits"] += 1
            kind = hit.get("kind", "")
            st["types"][kind] = st["types"].get(kind, 0) + 1
            if kind not in st["first"]:
                st["first"][kind] = {
                    "page": ev.get("page"), "rank": hit.get("rank"),
                    "global_rank": hit.get("global_rank"),
                    "url": hit.get("url", ""), "type": hit.get("type", TYPE_LABEL.get(kind, kind)),
                }

    def _render_all(self) -> None:
        self._render_results()
        self._render_class()
        self._update_hit_summary()

    def _render_results(self) -> None:
        self.results.setRowCount(0)
        selected_types = {k for k, cb in self.type_checks.items() if cb.isChecked()}
        for ev in self.page_events:
            row = self.results.rowCount()
            self.results.insertRow(row)
            self.results.setRowHeight(row, 44)
            hits = [h for h in (ev.get("hits") or []) if h.get("kind") in selected_types]
            all_hits = ev.get("hits") or []
            status = ev.get("status", "ok")
            values = [
                ev.get("brand", ""), ev.get("keyword", ""), ev.get("target_url", ""),
                ev.get("engine_label") or ENGINE_LABEL.get(ev.get("engine"), ""),
                str(ev.get("page", "")),
                {"ok": "完成", "no_results": "无结果", "captcha": "安全验证",
                 "network_error": "网络超时", "error": "页面异常"}.get(status, status),
                str(len(hits)),
                "、".join(
                    (f"自然#{h.get('global_rank') or h.get('rank')}"
                     if h.get("kind") == "organic" else h.get("type", ""))
                    for h in hits
                ) or ("—" if all_hits else "0 命中"),
                "查看" if ev.get("screenshot") else "—",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 2:
                    item.setForeground(QColor("#5A6B8A"))
                if col == 1:
                    font = QFont("Microsoft YaHei UI", 9)
                    font.setBold(True)
                    item.setFont(font)
                if col == 8 and ev.get("screenshot"):
                    item.setData(Qt.UserRole, ev.get("screenshot"))
                    item.setToolTip(Path(ev.get("screenshot") or "").name)
                    item.setForeground(QColor("#9A660F"))
                self.results.setItem(row, col, item)
            if hits:
                for col in range(self.results.columnCount()):
                    self.results.item(row, col).setBackground(QColor("#F3FBF7"))
            elif status in ("captcha", "network_error", "error"):
                for col in range(self.results.columnCount()):
                    self.results.item(row, col).setBackground(QColor("#FFF6F5"))

    def _render_class(self) -> None:
        self.class_table.setRowCount(0)
        for st in self.task_stats.values():
            for kind in ("brand", "card", "ad", "organic"):
                count = st["types"].get(kind, 0)
                if not count:
                    continue
                first = st["first"].get(kind, {})
                row = self.class_table.rowCount()
                self.class_table.insertRow(row)
                self.class_table.setRowHeight(row, 40)
                values = [
                    st["brand"], st["keyword"], st["engine"], TYPE_LABEL.get(kind, kind),
                    str(count), str(first.get("page", "")),
                    str(first.get("global_rank") or first.get("rank", "")
                        or first.get("type", "")),
                    first.get("url", ""),
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    if col == 3:
                        item.setForeground(QColor({"brand": "#A96A07", "card": "#3E68D8",
                                                    "ad": "#C24A45", "organic": "#1D8F66"}.get(kind, "#475467")))
                    self.class_table.setItem(row, col, item)

    def _update_hit_summary(self) -> None:
        total_hits = sum(st["hits"] for st in self.task_stats.values())
        hit_tasks = sum(1 for st in self.task_stats.values() if st["hits"])
        self.hit_summary.setText(
            f"命中 {total_hits} · 命中任务 {hit_tasks} · 页面 {len(self.page_events)}"
        )

    def _open_cell(self, row: int, col: int) -> None:
        if col == 8:
            item = self.results.item(row, 8)
            if item and item.data(Qt.UserRole):
                open_path(item.data(Qt.UserRole))
        elif col == 2:
            item = self.results.item(row, 2)
            if item:
                QDesktopServices.openUrl(QUrl(item.text()))

    def _stop(self) -> None:
        self.mark_stopping()
        self.main.stop_query()

    def _open_report(self) -> None:
        if self.report_path:
            open_path(self.report_path)

    def _open_dir(self) -> None:
        if getattr(self, "_row_dir", ""):
            open_path(self._row_dir)
