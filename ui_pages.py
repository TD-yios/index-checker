from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ui_shared import (
    StatStrip, ghost_button, link_button, make_page_head, open_path, primary_button,
)


def _panel(title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout, QHBoxLayout]:
    panel = QWidget()
    panel.setObjectName("Panel")
    panel.setAttribute(Qt.WA_StyledBackground, True)
    v = QVBoxLayout(panel)
    v.setContentsMargins(16, 14, 16, 12)
    v.setSpacing(10)
    top = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setStyleSheet("font-size:13px;font-weight:800;color:#252C3B;background:transparent;")
    top.addWidget(title_label)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Muted")
        top.addWidget(sub)
    top.addStretch(1)
    v.addLayout(top)
    return panel, v, top


class DashboardPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.library = main.library
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(12)

        self.import_btn = ghost_button("导入关键词")
        self.import_btn.clicked.connect(lambda: self.main.library_page.open_import())
        self.query_btn = primary_button("查询待查关键词")
        self.query_btn.clicked.connect(self._query_pending)
        head = make_page_head(
            "工作台",
            "先看还有多少关键词没查，再处理结果和报告；不做仪表盘堆叠，只保留要动手的事。",
            "今日工作",
            [self.import_btn, self.query_btn],
        )
        lay.addWidget(head)

        self.strip = StatStrip()
        lay.addWidget(self.strip)

        body = QHBoxLayout()
        body.setSpacing(12)

        left, left_lay, left_top = _panel("待查队列", "优先处理没有结果或还没查的关键词")
        self.pending_count = QLabel("")
        self.pending_count.setObjectName("Muted")
        left_top.addWidget(self.pending_count)
        self.all_kw_btn = link_button("全部关键词 →")
        self.all_kw_btn.clicked.connect(lambda: self.main.switch_page("library"))
        left_top.addWidget(self.all_kw_btn)
        self.pending_table = QTableWidget(0, 4)
        self.pending_table.setHorizontalHeaderLabels(["品牌", "关键词", "目标 URL", "状态"])
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.setShowGrid(False)
        self.pending_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.pending_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pending_table.setFocusPolicy(Qt.NoFocus)
        self.pending_table.setWordWrap(False)
        self.pending_table.cellDoubleClicked.connect(lambda *_: self.main.switch_page("library"))
        hh = self.pending_table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.pending_table.setColumnWidth(0, 88)
        self.pending_table.setColumnWidth(1, 130)
        self.pending_table.setColumnWidth(3, 66)
        left_lay.addWidget(self.pending_table, 1)
        self.pending_empty = QLabel("没有待查关键词，全部处理完了。")
        self.pending_empty.setObjectName("PageSub")
        self.pending_empty.setAlignment(Qt.AlignCenter)
        left_lay.addWidget(self.pending_empty)
        body.addWidget(left, 3)

        right, right_lay, right_top = _panel("最近报告", "查询结束后可直接打开")
        self.all_report_btn = link_button("全部报告 →")
        self.all_report_btn.clicked.connect(lambda: self.main.switch_page("reports"))
        right_top.addWidget(self.all_report_btn)
        self.report_list = QVBoxLayout()
        self.report_list.setSpacing(6)
        right_lay.addLayout(self.report_list)
        right_lay.addStretch(1)
        self.report_empty = QLabel("还没有报告，先跑一次查询。")
        self.report_empty.setObjectName("PageSub")
        self.report_empty.setWordWrap(True)
        right_lay.addWidget(self.report_empty)
        body.addWidget(right, 2)
        lay.addLayout(body, 1)

        self.bottom_note = QLabel("")
        self.bottom_note.setObjectName("Muted")
        self.bottom_note.setStyleSheet("font-size:10px;color:#98A2B3;")
        lay.addWidget(self.bottom_note)

    def refresh(self) -> None:
        records = self.library.all()
        counts = {"pending": 0, "hit": 0, "miss": 0, "error": 0}
        for r in records:
            status = r.get("last_status") or "pending"
            if status in ("pending", "running"):
                counts["pending"] += 1
            elif status in counts:
                counts[status] += 1
            else:
                counts["error"] += 1
        last = max((r.get("last_query_at", "") for r in records), default="")
        self.strip.set_values(
            len(records), len({r["brand"] for r in records}), counts["pending"],
            counts["hit"], counts["miss"], counts["error"],
            f"最近一次查询 {last}" if last else "还没有执行过查询",
        )
        self.query_btn.setEnabled(counts["pending"] > 0 and not self.main.is_running())
        self.query_btn.setText(f"查询待查关键词 {counts['pending']}" if counts["pending"] else "没有待查")
        self.pending_count.setText(f"{counts['pending']} 个")
        self._fill_pending([r for r in records if (r.get("last_status") or "pending") in ("pending", "running")])
        self._fill_reports()

    def _fill_pending(self, records: list[dict]) -> None:
        self.pending_table.setRowCount(0)
        shown = records[:8]
        for r in shown:
            row = self.pending_table.rowCount()
            self.pending_table.insertRow(row)
            self.pending_table.setRowHeight(row, 40)
            values = [r.get("brand", ""), r.get("keyword", ""), r.get("target_url", ""),
                      "查询中" if r.get("last_status") == "running" else "待查"]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 1:
                    font = QFont("Microsoft YaHei UI", 9)
                    font.setBold(True)
                    item.setFont(font)
                if col == 2:
                    item.setForeground(QColor("#5A6B8A"))
                if col == 3:
                    item.setForeground(QColor("#A96A07"))
                self.pending_table.setItem(row, col, item)
        self.pending_table.setVisible(bool(shown))
        self.pending_empty.setVisible(not shown)

    def _fill_reports(self) -> None:
        while self.report_list.count():
            item = self.report_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = self.main.report_entries()[:4]
        self.report_empty.setVisible(not entries)
        for entry in entries:
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 4, 0, 4)
            h.setSpacing(8)
            name = QLabel(entry["dir"].name)
            name.setStyleSheet("font-size:11px;font-weight:700;color:#344054;background:transparent;")
            name.setToolTip(str(entry["report"]))
            h.addWidget(name, 1)
            date = QLabel(entry["mtime"].strftime("%m-%d %H:%M"))
            date.setObjectName("Muted")
            h.addWidget(date)
            btn = link_button("打开")
            btn.clicked.connect(lambda _=False, p=entry["report"]: open_path(p))
            h.addWidget(btn)
            self.report_list.addWidget(row)

    def _query_pending(self) -> None:
        records = [r for r in self.library.all()
                   if (r.get("last_status") or "pending") in ("pending", "running")]
        if records:
            self.main.start_records(records)


class ReportsPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(12)
        self.refresh_btn = ghost_button("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        self.dir_btn = ghost_button("打开输出目录")
        self.dir_btn.clicked.connect(self._open_dir)
        head = make_page_head(
            "报告中心",
            "每次查询都会生成带品牌和目标 URL 的 Excel / CSV，截图和分页明细都在同目录。",
            "结果归档",
            [self.refresh_btn, self.dir_btn],
        )
        lay.addWidget(head)

        self.panel = QWidget()
        self.panel.setObjectName("Panel")
        self.panel.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "目录", "报告文件", "大小", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.cellDoubleClicked.connect(self._open_row)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for col, width in [(0, 130), (1, 260), (2, 220), (3, 90)]:
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        self.empty = QLabel("还没有报告。关键词库中勾选关键词并执行查询后，报告会出现在这里。")
        self.empty.setObjectName("PageSub")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        lay.addWidget(self.panel, 1)

        self.footer = QLabel("")
        self.footer.setObjectName("Muted")
        self.footer.setStyleSheet("font-size:10px;color:#98A2B3;")
        lay.addWidget(self.footer)

    def refresh(self) -> None:
        entries = self.main.report_entries()
        self._entries = entries
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, 44)
            values = [
                entry["mtime"].strftime("%Y-%m-%d %H:%M"),
                entry["dir"].name,
                entry["report"].name,
                f"{entry['size'] / 1024:.0f} KB",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 2:
                    item.setForeground(QColor("#5A6B8A"))
                self.table.setItem(row, col, item)
            action = QWidget()
            action.setStyleSheet("background:transparent;")
            h = QHBoxLayout(action)
            h.setContentsMargins(0, 0, 4, 0)
            h.setSpacing(6)
            open_btn = QPushButton("打开报告")
            open_btn.setObjectName("RowPrimary")
            open_btn.setCursor(Qt.PointingHandCursor)
            open_btn.clicked.connect(lambda _=False, p=entry["report"]: open_path(p))
            folder_btn = QPushButton("目录")
            folder_btn.setObjectName("RowGhost")
            folder_btn.setCursor(Qt.PointingHandCursor)
            folder_btn.clicked.connect(lambda _=False, p=entry["dir"]: open_path(p))
            h.addWidget(open_btn)
            h.addWidget(folder_btn)
            h.addStretch(1)
            self.table.setCellWidget(row, 4, action)
        self.empty.setVisible(not entries)
        self.table.setVisible(bool(entries))
        base = self.main.outdir_base()
        self.footer.setText(f"共 {len(entries)} 份报告 · 当前输出目录：{base}")

    def _open_row(self, row: int, col: int) -> None:
        entries = getattr(self, "_entries", [])
        if 0 <= row < len(entries):
            open_path(entries[row]["report"])

    def _open_dir(self) -> None:
        open_path(self.main.outdir_base())
