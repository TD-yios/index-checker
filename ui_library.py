from __future__ import annotations

from collections import OrderedDict
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.config import normalize_domain
from ui_dialogs import BrandRenameDialog, ImportDialog, KeywordDialog
from ui_shared import (
    ENGINE_ORDER, ENGINE_LABEL, StatStrip, danger_button, ghost_button, link_button, make_page_head,
    primary_button,
)

STATUS_LABEL = {
    "pending": ("待查", "StatusPending"),
    "running": ("查询中", "StatusRunning"),
    "hit": ("已命中", "StatusHit"),
    "miss": ("未命中", "StatusMiss"),
    "error": ("异常", "StatusError"),
}


class LibraryPage(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.library = main.library
        self.records: list[dict[str, Any]] = []
        self.visible_records: list[dict[str, Any]] = []
        self.selected_ids: set[int] = set()
        self.current_filter = "all"
        self.search_text = ""
        self.row_checks: dict[int, QPushButton] = {}
        self.group_checks: dict[str, QPushButton] = {}
        self.ids_by_brand: dict[str, list[int]] = {}
        self.row_ids: dict[int, int] = {}
        self.brand_colors: dict[str, str] = {}
        self._syncing = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(12)

        self.import_btn = ghost_button("导入关键词")
        self.import_btn.clicked.connect(self.open_import)
        self.add_btn = primary_button("新增关键词")
        self.add_btn.clicked.connect(self.open_add)
        self.head = make_page_head(
            "关键词库",
            "按品牌维护关键词和目标 URL；勾选后批量查询收录，优先处理待查和未命中。",
            "关键词资产",
            [self.import_btn, self.add_btn],
        )
        lay.addWidget(self.head)

        self.strip = StatStrip()
        lay.addWidget(self.strip)

        self.panel = QWidget()
        self.panel.setObjectName("Panel")
        self.panel.setAttribute(Qt.WA_StyledBackground, True)
        panel_lay = QVBoxLayout(self.panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(0)

        toolbar = QWidget()
        toolbar.setObjectName("Toolbar")
        toolbar.setAttribute(Qt.WA_StyledBackground, True)
        toolbar_lay = QHBoxLayout(toolbar)
        toolbar_lay.setContentsMargins(18, 11, 18, 11)
        toolbar_lay.setSpacing(12)
        tabs_box = QWidget()
        tabs_box.setObjectName("TabsBox")
        tabs_box.setAttribute(Qt.WA_StyledBackground, True)
        tabs_lay = QHBoxLayout(tabs_box)
        tabs_lay.setContentsMargins(3, 3, 3, 3)
        tabs_lay.setSpacing(2)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, text in [("all", "全部"), ("pending", "待查"), ("hit", "已命中"),
                          ("miss", "未命中"), ("error", "异常")]:
            btn = QPushButton(text)
            btn.setObjectName("FilterTab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.filter_group.addButton(btn)
            tabs_lay.addWidget(btn)
            self.filter_buttons[key] = btn
        self.filter_buttons["all"].setChecked(True)
        toolbar_lay.addWidget(tabs_box)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索品牌 / 关键词 / 目标 URL")
        self.search.setFixedWidth(250)
        self.search.textChanged.connect(self._on_search)
        toolbar_lay.addWidget(self.search)
        toolbar_lay.addStretch(1)
        panel_lay.addWidget(toolbar)

        batch = QWidget()
        batch.setObjectName("BatchBar")
        batch.setAttribute(Qt.WA_StyledBackground, True)
        batch_lay = QHBoxLayout(batch)
        batch_lay.setContentsMargins(18, 9, 18, 9)
        batch_lay.setSpacing(11)
        self.select_all = QCheckBox("全选")
        self.select_all.setTristate(True)
        self.select_all.stateChanged.connect(self._select_all_changed)
        batch_lay.addWidget(self.select_all)
        self.selected_label = QLabel("勾选关键词后可批量查询")
        self.selected_label.setObjectName("SelectedText")
        self.selected_label.setStyleSheet("font-size:11px;color:#667085;")
        self.selected_label.setTextFormat(Qt.RichText)
        batch_lay.addWidget(self.selected_label)

        actions_box = QWidget()
        actions_box.setStyleSheet("background:transparent;")
        actions = QHBoxLayout(actions_box)
        actions.setContentsMargins(10, 0, 0, 0)
        actions.setSpacing(7)
        self.query_btn = primary_button("批量查询")
        self.query_btn.clicked.connect(self._query_selected)
        self.edit_btn = ghost_button("编辑")
        self.edit_btn.clicked.connect(self._edit_selected)
        self.delete_btn = danger_button("删除")
        self.delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(self.query_btn)
        actions.addWidget(self.edit_btn)
        actions.addWidget(self.delete_btn)
        batch_lay.addWidget(actions_box)

        batch_lay.addStretch(1)
        self.mode_label = QLabel("")
        self.mode_label.setObjectName("Muted")
        batch_lay.addWidget(self.mode_label)
        panel_lay.addWidget(batch)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("LibraryTable")
        self.table.setHorizontalHeaderLabels(["", "关键词", "目标 URL", "最近查询", "状态", "命中分布", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.cellDoubleClicked.connect(self._open_cell)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        for col, width in [(0, 40), (1, 200), (3, 130), (4, 100), (5, 190), (6, 122)]:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.stack.addWidget(self.table)

        self.empty = QWidget()
        empty_lay = QVBoxLayout(self.empty)
        empty_lay.setContentsMargins(20, 60, 20, 60)
        empty_lay.setSpacing(8)
        empty_lay.setAlignment(Qt.AlignCenter)
        empty_title = QLabel("还没有关键词")
        empty_title.setObjectName("PageTitle")
        empty_title.setStyleSheet("font-size:16px;")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_sub = QLabel("先导入一批品牌关键词和对应目标 URL，再开始查收录。快捷键：Ctrl+I 导入，Ctrl+N 新增。")
        empty_sub.setObjectName("PageSub")
        empty_sub.setAlignment(Qt.AlignCenter)
        empty_btn = primary_button("导入关键词")
        empty_btn.clicked.connect(self.open_import)
        empty_lay.addWidget(empty_title)
        empty_lay.addWidget(empty_sub)
        empty_lay.addSpacing(6)
        empty_lay.addWidget(empty_btn, 0, Qt.AlignCenter)
        self.stack.addWidget(self.empty)
        panel_lay.addWidget(self.stack, 1)

        footer = QWidget()
        footer.setObjectName("Footer")
        footer.setStyleSheet("background:#FBFCFE;border-top:1px solid #EEF1F5;")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(18, 8, 18, 8)
        self.footer_left = QLabel("")
        self.footer_left.setObjectName("Muted")
        self.footer_left.setStyleSheet("font-size:10px;color:#8A94A6;")
        self.footer_right = QLabel("按品牌分组 · 每词独立 URL · Ctrl+F 搜索")
        self.footer_right.setObjectName("Muted")
        self.footer_right.setStyleSheet("font-size:10px;color:#8A94A6;")
        footer_lay.addWidget(self.footer_left)
        footer_lay.addStretch(1)
        footer_lay.addWidget(self.footer_right)
        panel_lay.addWidget(footer)

        lay.addWidget(self.panel, 1)
        self.update_mode_label()

    # ---------------- data ----------------
    def refresh(self) -> None:
        self.records = self.library.all()
        brands = sorted({r["brand"] for r in self.records})
        palette = ["#F59E0B", "#4F7DF3", "#20AF7B", "#7355C9", "#D9534F", "#0EA5E9"]
        self.brand_colors = {b: palette[i % len(palette)] for i, b in enumerate(brands)}
        last = max((r.get("last_query_at", "") for r in self.records), default="")
        counts = self._counts()
        self.strip.set_values(
            len(self.records), len(brands), counts["pending"], counts["hit"],
            counts["miss"], counts["error"],
            f"最近一次查询 {last}" if last else "还没有执行过查询",
        )
        for key in ("all", "pending", "hit", "miss", "error"):
            self.filter_buttons[key].setText(f"{self._filter_label(key)} {counts.get(key, 0)}")
        self._rebuild()
        self.update_mode_label()

    def _counts(self) -> dict[str, int]:
        counts = {"all": len(self.records), "pending": 0, "hit": 0, "miss": 0, "error": 0}
        for r in self.records:
            status = r.get("last_status") or "pending"
            if status in ("pending", "running"):
                counts["pending"] += 1
            elif status in counts:
                counts[status] += 1
            else:
                counts["error"] += 1
        return counts

    @staticmethod
    def _filter_label(key: str) -> str:
        return {"all": "全部", "pending": "待查", "hit": "已命中",
                "miss": "未命中", "error": "异常"}[key]

    def _filtered_records(self) -> list[dict[str, Any]]:
        term = self.search_text.strip().lower()
        result = []
        for r in self.records:
            status = r.get("last_status") or "pending"
            if self.current_filter == "pending":
                status_ok = status in ("pending", "running")
            elif self.current_filter != "all":
                status_ok = status == self.current_filter
            else:
                status_ok = True
            if not status_ok:
                continue
            text = f"{r.get('brand','')} {r.get('keyword','')} {r.get('target_url','')}".lower()
            if term and term not in text:
                continue
            result.append(r)
        return result

    def _set_filter(self, key: str) -> None:
        self.current_filter = key
        self.filter_buttons[key].setChecked(True)
        self._rebuild()

    def _on_search(self, text: str) -> None:
        self.search_text = text
        self._rebuild()

    # ---------------- table ----------------
    def _rebuild(self) -> None:
        self.table.setRowCount(0)
        self.table.clearSpans()
        self.table.clearContents()
        self.row_checks.clear()
        self.group_checks.clear()
        self.ids_by_brand.clear()
        self.row_ids.clear()
        self.visible_records = self._filtered_records()

        if not self.records:
            self.stack.setCurrentWidget(self.empty)
            self.footer_left.setText("共 0 个关键词 · 0 个品牌")
            self._refresh_batch()
            return
        self.stack.setCurrentWidget(self.table)
        if not self.visible_records:
            self.footer_left.setText("当前筛选没有关键词 · 共 "
                                     f"{len(self.records)} 个关键词 / {len({r['brand'] for r in self.records})} 个品牌")
            self._refresh_batch()
            return

        groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for r in self.visible_records:
            groups.setdefault(r["brand"], []).append(r)
        for brand, group in groups.items():
            self._insert_group_header(brand, group)
            for record in group:
                self._insert_record_row(record)

        self.footer_left.setText(
            f"共 {len(self.records)} 个关键词 · {len({r['brand'] for r in self.records})} 个品牌 · "
            f"当前显示 {len(self.visible_records)} 个"
        )
        self._refresh_batch()

    def _make_check(self) -> QPushButton:
        btn = QPushButton("")
        btn.setObjectName("RowCheck")
        btn.setCheckable(True)
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.PointingHandCursor)
        btn.toggled.connect(lambda checked, b=btn: b.setText("✓" if checked else ""))
        return btn

    def _insert_group_header(self, brand: str, group: list[dict[str, Any]]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setSpan(row, 0, 1, 7)
        self.table.setRowHeight(row, 42)
        header = QWidget()
        header.setObjectName("BrandGroupHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 12, 0)
        h.setSpacing(8)
        accent = QLabel()
        accent.setFixedSize(3, 26)
        accent.setStyleSheet(f"background:{self.brand_colors.get(brand, '#D0D5DD')};border-radius:1px;")
        h.addWidget(accent)
        check = self._make_check()
        ids = [int(r["id"]) for r in group]
        self.group_checks[brand] = check
        self.ids_by_brand[brand] = ids
        check.toggled.connect(lambda checked, b=brand: self._toggle_group(b, checked))
        h.addWidget(check)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background:{self.brand_colors.get(brand, '#D0D5DD')};border-radius:2px;")
        h.addWidget(dot)
        name = QLabel(brand)
        name.setObjectName("BrandGroupName")
        h.addWidget(name)
        count = QLabel(f"{len(group)} 个关键词")
        count.setObjectName("GroupCount")
        h.addWidget(count)
        domains = sorted({r.get("target_domain") or normalize_domain(r.get("target_url", "")) for r in group})
        urls = QLabel(" · ".join(d for d in domains if d))
        urls.setObjectName("GroupUrls")
        urls.setToolTip("\n".join(r.get("target_url", "") for r in group))
        h.addWidget(urls)
        h.addStretch(1)
        rename_brand = link_button("重命名")
        rename_brand.clicked.connect(lambda _=False, b=brand, c=len(group): self._rename_brand(b, c))
        h.addWidget(rename_brand)
        query_brand = link_button("查询本品牌")
        query_brand.clicked.connect(lambda _=False, b=brand: self._query_brand(b))
        h.addWidget(query_brand)
        self.table.setCellWidget(row, 0, header)
        self.table.setRowHeight(row, 38)

    def _insert_record_row(self, record: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 48)
        record_id = int(record["id"])
        self.row_ids[row] = record_id
        for col in range(7):
            item = QTableWidgetItem("")
            item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, col, item)

        check = self._make_check()
        self.row_checks[record_id] = check
        check.setChecked(record_id in self.selected_ids)
        check.toggled.connect(lambda checked, rid=record_id: self._toggle_record(rid, checked))
        check_wrap = QWidget()
        check_wrap.setStyleSheet("background:transparent;")
        cw = QHBoxLayout(check_wrap)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.addWidget(check, 0, Qt.AlignCenter)
        self.table.setCellWidget(row, 0, check_wrap)

        keyword_item = QTableWidgetItem(record.get("keyword", ""))
        keyword_item.setData(Qt.UserRole, record_id)
        keyword_item.setToolTip(record.get("keyword", ""))
        font = QFont("Microsoft YaHei UI", 10)
        font.setBold(True)
        keyword_item.setFont(font)
        keyword_item.setForeground(QColor("#252C3B"))
        self.table.setItem(row, 1, keyword_item)

        url_item = QTableWidgetItem("↗  " + record.get("target_url", ""))
        url_item.setData(Qt.UserRole, record.get("target_url", ""))
        url_item.setToolTip(record.get("target_url", ""))
        url_item.setForeground(QColor("#5A6B8A"))
        self.table.setItem(row, 2, url_item)

        date_wrap = QWidget()
        date_wrap.setStyleSheet("background:transparent;")
        dv = QVBoxLayout(date_wrap)
        dv.setContentsMargins(11, 4, 4, 4)
        dv.setSpacing(1)
        date = QLabel(record.get("last_query_at") or "未查询")
        date.setStyleSheet("font-size:11px;font-weight:600;color:#4D596C;background:transparent;")
        engine = QLabel(record.get("last_engine") or "—")
        engine.setStyleSheet("font-size:9px;color:#98A2B3;background:transparent;")
        dv.addWidget(date)
        dv.addWidget(engine)
        self.table.setCellWidget(row, 3, date_wrap)

        status_wrap = QWidget()
        status_wrap.setStyleSheet("background:transparent;")
        sv = QHBoxLayout(status_wrap)
        sv.setContentsMargins(8, 0, 4, 0)
        text, object_name = STATUS_LABEL.get(record.get("last_status") or "pending", STATUS_LABEL["pending"])
        status = QLabel(text)
        status.setObjectName(object_name)
        sv.addWidget(status)
        sv.addStretch(1)
        self.table.setCellWidget(row, 4, status_wrap)

        hits_wrap = QWidget()
        hits_wrap.setStyleSheet("background:transparent;")
        hv = QHBoxLayout(hits_wrap)
        hv.setContentsMargins(8, 0, 4, 0)
        hv.setSpacing(4)
        summary = record.get("last_summary") or ""
        if not summary or (record.get("last_status") == "pending"):
            empty_hit = QLabel("—")
            empty_hit.setStyleSheet("font-size:10px;color:#B0B7C4;background:transparent;")
            hv.addWidget(empty_hit)
        elif summary in ("0 命中", "—"):
            empty_hit = QLabel("0 命中")
            empty_hit.setObjectName("TagGray")
            hv.addWidget(empty_hit)
        else:
            for part in summary.split(" · "):
                label = QLabel(part)
                if part.startswith("品牌"):
                    label.setObjectName("TagBrand")
                elif part.startswith("卡片"):
                    label.setObjectName("TagCard")
                elif part.startswith("竞价"):
                    label.setObjectName("TagAd")
                elif part.startswith("自然"):
                    label.setObjectName("TagOrganic")
                else:
                    label.setObjectName("TagGray")
                hv.addWidget(label)
        hv.addStretch(1)
        self.table.setCellWidget(row, 5, hits_wrap)

        action_wrap = QWidget()
        action_wrap.setStyleSheet("background:transparent;")
        av = QHBoxLayout(action_wrap)
        av.setContentsMargins(5, 0, 5, 0)
        av.setSpacing(5)
        run = QPushButton("查询")
        run.setObjectName("RowPrimary")
        run.setCursor(Qt.PointingHandCursor)
        run.clicked.connect(lambda _=False, r=record: self.main.start_records([r]))
        edit = QPushButton("编辑")
        edit.setObjectName("RowGhost")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda _=False, r=record: self._edit_record(r))
        av.addWidget(run)
        av.addWidget(edit)
        self.table.setCellWidget(row, 6, action_wrap)

    # ---------------- selection ----------------
    def _toggle_record(self, record_id: int, checked: bool) -> None:
        if checked:
            self.selected_ids.add(record_id)
        else:
            self.selected_ids.discard(record_id)
        self._refresh_batch()

    def _toggle_group(self, brand: str, checked: bool) -> None:
        for rid in self.ids_by_brand.get(brand, []):
            if checked:
                self.selected_ids.add(rid)
            else:
                self.selected_ids.discard(rid)
        self._refresh_batch()

    def _select_all_changed(self, state: int) -> None:
        if self._syncing:
            return
        checked = self.select_all.checkState() == Qt.Checked
        for r in self.visible_records:
            rid = int(r["id"])
            if checked:
                self.selected_ids.add(rid)
            else:
                self.selected_ids.discard(rid)
        self._refresh_batch()

    def _refresh_batch(self) -> None:
        self._syncing = True
        visible_ids = {int(r["id"]) for r in self.visible_records}
        selected = [r for r in self.visible_records if int(r["id"]) in self.selected_ids]
        if selected:
            brands = {r["brand"] for r in selected}
            self.selected_label.setText(
                f"已选 <b>{len(selected)}</b> 个关键词 · 覆盖 <b>{len(brands)}</b> 个品牌"
            )
        else:
            self.selected_label.setText("当前筛选下未选择关键词")
        self.query_btn.setText(f"批量查询 {len(selected)}" if selected else "批量查询")
        self.query_btn.setEnabled(bool(selected))
        self.edit_btn.setEnabled(len(selected) == 1)
        self.delete_btn.setEnabled(bool(selected))

        visible_selected = {rid for rid in visible_ids if rid in self.selected_ids}
        for rid, check in self.row_checks.items():
            if rid not in visible_ids:
                continue
            check.blockSignals(True)
            check.setChecked(rid in self.selected_ids)
            check.setText("✓" if check.isChecked() else "")
            check.blockSignals(False)
        for brand, check in self.group_checks.items():
            ids = self.ids_by_brand.get(brand, [])
            chosen = [rid for rid in ids if rid in self.selected_ids]
            check.blockSignals(True)
            check.setChecked(bool(ids) and len(chosen) == len(ids))
            check.setText("✓" if check.isChecked() else "")
            check.blockSignals(False)
        self.select_all.blockSignals(True)
        if not visible_ids:
            self.select_all.setCheckState(Qt.Unchecked)
        elif len(visible_selected) == len(visible_ids):
            self.select_all.setCheckState(Qt.Checked)
        elif visible_selected:
            self.select_all.setCheckState(Qt.PartiallyChecked)
        else:
            self.select_all.setCheckState(Qt.Unchecked)
        self.select_all.blockSignals(False)
        self._syncing = False

    def select_ids(self, ids: list[int]) -> None:
        self.selected_ids.update(int(x) for x in ids)
        self._refresh_batch()

    def clear_selection(self) -> None:
        self.selected_ids.clear()
        self._refresh_batch()

    # ---------------- actions ----------------
    def update_mode_label(self) -> None:
        defaults = self.main.query_defaults()
        engines = [ENGINE_LABEL[n] for n in ENGINE_ORDER
                   if (defaults.get("engines") or {}).get(n)]
        self.mode_label.setText(f"引擎：{' + '.join(engines) or '未选择'} · {defaults.get('pages', 2)} 页")

    def open_import(self) -> None:
        dlg = ImportDialog(self.library, self)
        if dlg.exec() == QDialog.Accepted:
            self.selected_ids.clear()
            self.main.after_library_change()

    def open_add(self) -> None:
        dlg = KeywordDialog(self.library, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.main.after_library_change()

    def _edit_record(self, record: dict[str, Any]) -> None:
        dlg = KeywordDialog(self.library, record, self)
        if dlg.exec() == QDialog.Accepted:
            self.main.after_library_change()

    def _edit_selected(self) -> None:
        records = [r for r in self.visible_records if int(r["id"]) in self.selected_ids]
        if len(records) != 1:
            QMessageBox.information(self, "提示", "一次只编辑一个关键词。")
            return
        self._edit_record(records[0])

    def _rename_brand(self, brand: str, count: int) -> None:
        dlg = BrandRenameDialog(self.library, brand, count, self)
        if dlg.exec() == QDialog.Accepted:
            self.selected_ids.clear()
            self.main.after_library_change()
            self.main.dashboard_page.refresh()
            self.main.reports_page.refresh()

    def _delete_selected(self) -> None:
        records = [r for r in self.visible_records if int(r["id"]) in self.selected_ids]
        if not records:
            return
        answer = QMessageBox.question(
            self, "删除关键词",
            f"确定删除选中的 {len(records)} 个关键词？此操作不会删除历史报告。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.library.delete([int(r["id"]) for r in records])
        self.selected_ids.difference_update(int(r["id"]) for r in records)
        self.main.after_library_change()

    def _query_selected(self) -> None:
        records = [r for r in self.visible_records if int(r["id"]) in self.selected_ids]
        if records:
            self.main.start_records(records)

    def _query_brand(self, brand: str) -> None:
        records = [r for r in self.records if r["brand"] == brand]
        if records:
            self.main.start_records(records)

    def _open_cell(self, row: int, col: int) -> None:
        record_id = self.row_ids.get(row)
        if not record_id:
            return
        record = next((r for r in self.visible_records if int(r["id"]) == record_id), None)
        if record is None:
            return
        if col == 1:
            self._edit_record(record)
        elif col == 2:
            QDesktopServices.openUrl(QUrl(record.get("target_url", "")))

    def _open_url(self, record: dict[str, Any]) -> None:
        QDesktopServices.openUrl(QUrl(record.get("target_url", "")))
