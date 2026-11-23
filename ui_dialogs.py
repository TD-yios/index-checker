from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QSettings, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.library import KeywordLibrary, normalize_target_url
from core.proxy import test_proxy
from ui_shared import (
    APP_AUTHOR, APP_COPYRIGHT, APP_GITHUB_HANDLE, APP_GITHUB_URL, APP_NAME, APP_VERSION,
    ENGINE_ORDER, browser_summary, danger_button, default_outdir, ghost_button,
    primary_button, remember_good_proxy,
)
from core.config import ENGINE_LABEL


def _read_text_smart(path: Path) -> str:
    """Excel 导出的 CSV/TXT 有时是 GBK，按 UTF-8 读取失败时自动回退。"""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error or ValueError("文件编码无法识别")


def _read_csv_smart(path: Path) -> list[list[str]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.reader(f))
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error or ValueError("CSV 编码无法识别")


class ProxyTestThread(QThread):
    """在后台检查代理能否访问对应引擎，避免卡住查询设置窗口。"""

    result = Signal(str, bool, str)

    def __init__(self, engine: str, proxy: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.proxy = proxy

    def run(self) -> None:
        try:
            code, elapsed = test_proxy(self.proxy, self.engine, timeout=8)
            self.result.emit(self.engine, True, f"可访问 · HTTP {code} · {elapsed:.2f}s")
        except Exception as exc:
            self.result.emit(self.engine, False, f"失败：{exc}")


_ACTIVE_PROXY_TESTS: set[ProxyTestThread] = set()


class KeywordDialog(QDialog):
    def __init__(self, library: KeywordLibrary, record: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.library = library
        self.record = record
        self.result_record: dict[str, Any] | None = None
        self.setWindowTitle("编辑关键词" if record else "新增关键词")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        title = QLabel("编辑关键词" if record else "新增关键词")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:19px;")
        lay.addWidget(title)
        sub = QLabel("同品牌下关键词唯一；品牌、关键词和目标 URL 都可修改。")
        sub.setObjectName("PageSub")
        lay.addWidget(sub)

        card = QWidget()
        card.setObjectName("Panel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        form = QGridLayout(card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)

        self.brand_edit = QLineEdit((record or {}).get("brand", ""))
        self.keyword_edit = QLineEdit((record or {}).get("keyword", ""))
        self.url_edit = QLineEdit((record or {}).get("target_url", ""))
        self.url_edit.setPlaceholderText("https://www.example.com")
        for row, (label, edit) in enumerate([
            ("品牌", self.brand_edit), ("关键词", self.keyword_edit), ("目标 URL", self.url_edit),
        ]):
            lab = QLabel(label)
            lab.setObjectName("FieldLabel")
            lab.setStyleSheet("font-size:11px;font-weight:700;color:#475467;")
            form.addWidget(lab, row, 0)
            form.addWidget(edit, row, 1)
        form.setColumnStretch(1, 1)
        lay.addWidget(card)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ghost_button("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        lay.addLayout(footer)

    def _save(self) -> None:
        try:
            if self.record:
                self.library.update_record(
                    int(self.record["id"]),
                    self.brand_edit.text(),
                    self.keyword_edit.text(),
                    self.url_edit.text(),
                )
                self.result_record = self.library.get(int(self.record["id"]))
            else:
                self.result_record = self.library.add(
                    self.brand_edit.text(), self.keyword_edit.text(), self.url_edit.text()
                )
        except Exception as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self.accept()


class BrandRenameDialog(QDialog):
    """品牌重命名 / 合并；合并时保留目标品牌已有词，删除重复来源词。"""

    def __init__(self, library: KeywordLibrary, brand: str, count: int, parent=None):
        super().__init__(parent)
        self.library = library
        self.brand = brand
        self.setWindowTitle("重命名 / 合并品牌")
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        title = QLabel("重命名 / 合并品牌")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:19px;")
        lay.addWidget(title)
        sub = QLabel(f"当前品牌「{brand}」下有 {count} 个关键词。改成已有品牌时，可选择合并。")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        card = QWidget()
        card.setObjectName("Panel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        form = QGridLayout(card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        old_label = QLabel("原品牌")
        old_label.setStyleSheet("font-size:11px;font-weight:700;color:#475467;")
        old_edit = QLineEdit(brand)
        old_edit.setReadOnly(True)
        new_label = QLabel("新品牌")
        new_label.setStyleSheet("font-size:11px;font-weight:700;color:#475467;")
        self.new_edit = QLineEdit(brand)
        self.new_edit.setPlaceholderText("输入新的品牌名称")
        self.new_edit.selectAll()
        form.addWidget(old_label, 0, 0)
        form.addWidget(old_edit, 0, 1)
        form.addWidget(new_label, 1, 0)
        form.addWidget(self.new_edit, 1, 1)
        form.setColumnStretch(1, 1)
        lay.addWidget(card)

        note = QLabel("重命名会移动该品牌下所有关键词；目标品牌已有同名词时，合并只保留目标品牌那一份。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ghost_button("取消")
        cancel.clicked.connect(self.reject)
        save = primary_button("保存")
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        lay.addLayout(footer)

    def _save(self) -> None:
        new_brand = self.new_edit.text().strip()
        if not new_brand:
            QMessageBox.warning(self, "品牌名", "新品牌不能为空。")
            return
        if new_brand == self.brand:
            self.accept()
            return
        try:
            moved, merged = self.library.rename_brand(self.brand, new_brand, merge=False)
        except ValueError as exc:
            if "请选择合并" not in str(exc):
                QMessageBox.warning(self, "无法重命名", str(exc))
                return
            answer = QMessageBox.question(
                self, "合并品牌",
                f"目标品牌「{new_brand}」下已有同名关键词。\n"
                "继续合并会保留目标品牌已有词，并删除本品牌中的重复词。确定合并吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                moved, merged = self.library.rename_brand(self.brand, new_brand, merge=True)
            except Exception as merge_exc:
                QMessageBox.warning(self, "合并失败", str(merge_exc))
                return
        except Exception as exc:
            QMessageBox.warning(self, "无法重命名", str(exc))
            return
        QMessageBox.information(
            self, "完成",
            f"已移动到「{new_brand}」：{moved} 个关键词"
            + (f"，合并删除重复词 {merged} 个。" if merged else "。"),
        )
        self.accept()


class ImportDialog(QDialog):
    def __init__(self, library: KeywordLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self.parsed: list[dict[str, str]] = []
        self.file_rows: list[list[Any]] | None = None
        self.setWindowTitle("导入关键词")
        self.resize(800, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("导入关键词")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:19px;")
        lay.addWidget(title)
        sub = QLabel("每行三列：品牌、关键词、目标 URL；导入前先校验，重复词和坏 URL 不会进入库。")
        sub.setObjectName("PageSub")
        lay.addWidget(sub)

        card = QWidget()
        card.setObjectName("Panel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        body = QVBoxLayout(card)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(9)

        format_label = QLabel(
            "格式：<b>品牌,关键词,目标URL</b>　支持 http/https 或裸域名；重复按“品牌 + 关键词”判断"
        )
        format_label.setObjectName("Muted")
        format_label.setStyleSheet("font-size:10.5px;color:#667085;")
        format_label.setTextFormat(Qt.RichText)
        body.addWidget(format_label)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "示例品牌,示例品牌,https://www.example.com\n"
            "示例品牌B,示例品牌B,https://www.example.org"
        )
        self.text_edit.setFixedHeight(104)
        self.text_edit.textChanged.connect(self._text_changed)
        body.addWidget(self.text_edit)

        file_row = QHBoxLayout()
        choose = ghost_button("选择 Excel / CSV / TXT")
        choose.clicked.connect(self._choose_file)
        self.file_label = QLabel("也可以直接选择表格文件")
        self.file_label.setObjectName("Muted")
        file_row.addWidget(choose)
        file_row.addWidget(self.file_label, 1)
        validate = primary_button("校验数据")
        validate.clicked.connect(self._validate)
        file_row.addWidget(validate)
        body.addLayout(file_row)

        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["品牌", "关键词", "目标 URL", "校验"])
        self.preview.verticalHeader().setVisible(False)
        self.preview.setShowGrid(False)
        self.preview.setWordWrap(False)
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.preview.setColumnWidth(0, 120)
        self.preview.setColumnWidth(1, 165)
        self.preview.setColumnWidth(2, 285)
        preview_header = self.preview.horizontalHeader()
        preview_header.setStretchLastSection(False)
        preview_header.setSectionResizeMode(2, QHeaderView.Stretch)
        preview_header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.preview.setColumnWidth(3, 145)
        self.preview.setFixedHeight(230)
        body.addWidget(self.preview)

        self.status_label = QLabel("等待校验")
        self.status_label.setObjectName("Muted")
        body.addWidget(self.status_label)
        lay.addWidget(card)
        lay.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ghost_button("取消")
        cancel.clicked.connect(self.reject)
        self.import_btn = primary_button("导入")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import)
        footer.addWidget(cancel)
        footer.addWidget(self.import_btn)
        lay.addLayout(footer)

    def _text_changed(self) -> None:
        if self.file_rows is not None:
            self.file_rows = None
            self.file_label.setText("已切换到粘贴文本")

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择关键词文件", "", "表格 / 文本 (*.xlsx *.xlsm *.csv *.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        p = Path(path)
        try:
            if p.suffix.lower() in (".xlsx", ".xlsm"):
                from openpyxl import load_workbook
                wb = load_workbook(p, read_only=True, data_only=True)
                ws = wb.active
                self.file_rows = [list(row) for row in ws.iter_rows(values_only=True)]
                wb.close()
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText("")
                self.text_edit.blockSignals(False)
            elif p.suffix.lower() == ".csv":
                self.file_rows = _read_csv_smart(p)
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText("")
                self.text_edit.blockSignals(False)
            else:
                text = _read_text_smart(p)
                self.file_rows = None
                self.text_edit.setPlainText(text)
            self.file_label.setText(f"已选择：{p.name}")
            self._validate()
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))

    def _validate(self) -> None:
        if self.file_rows is not None:
            self.parsed = self.library.parse_import_rows(self.file_rows)
        else:
            self.parsed = self.library.parse_import_text(self.text_edit.toPlainText())
        self.preview.setRowCount(0)
        valid = duplicate = invalid = 0
        for item in self.parsed:
            row = self.preview.rowCount()
            self.preview.insertRow(row)
            for col, value in enumerate([
                item.get("brand", ""), item.get("keyword", ""),
                item.get("target_url", ""), item.get("message", ""),
            ]):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.preview.setItem(row, col, cell)
            check = item.get("check")
            if check == "valid":
                valid += 1
                self.preview.item(row, 3).setForeground(Qt.darkGreen)
            elif check == "duplicate":
                duplicate += 1
                self.preview.item(row, 3).setForeground(Qt.darkYellow)
            else:
                invalid += 1
                self.preview.item(row, 3).setForeground(Qt.red)
        self.status_label.setText(f"{len(self.parsed)} 行数据 · {valid} 行可导入 · {duplicate} 行重复 · {invalid} 行无效")
        self.import_btn.setEnabled(valid > 0)
        self.import_btn.setText(f"导入 {valid} 个关键词" if valid else "导入")

    def _import(self) -> None:
        try:
            added = self.library.import_valid(self.parsed)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        QMessageBox.information(self, "导入完成", f"已导入 {added} 个关键词。")
        self.accept()


class QueryConfigDialog(QDialog):
    def __init__(self, defaults: dict[str, Any], record_count: int, brand_count: int, parent=None):
        super().__init__(parent)
        self.defaults = defaults
        self.settings = QSettings("IndexChecker", "IndexChecker")
        self._last_good = dict(defaults.get("last_good_proxies") or {})
        self.setWindowTitle("查询设置")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("查询设置")
        title.setObjectName("PageTitle")
        title.setStyleSheet("font-size:19px;")
        lay.addWidget(title)
        sub = QLabel(f"本次将查询 {record_count} 个关键词，覆盖 {brand_count} 个品牌。每个关键词使用自己的目标 URL。")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        engine_box = QGroupBox("搜索引擎")
        engine_lay = QHBoxLayout(engine_box)
        engine_lay.setContentsMargins(12, 14, 12, 10)
        self.engine_checks: dict[str, QCheckBox] = {}
        for name in ENGINE_ORDER:
            cb = QCheckBox(ENGINE_LABEL[name])
            cb.setChecked(bool((defaults.get("engines") or {}).get(name, name != "google")))
            self.engine_checks[name] = cb
            engine_lay.addWidget(cb)
        engine_lay.addStretch(1)
        lay.addWidget(engine_box)

        opts_box = QGroupBox("查询范围")
        opts = QGridLayout(opts_box)
        opts.setContentsMargins(12, 14, 12, 10)
        opts.setHorizontalSpacing(12)
        opts.setVerticalSpacing(8)
        opts.setColumnStretch(2, 1)
        opts.addWidget(QLabel("翻页次数"), 0, 0)
        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(1, 20)
        self.pages_spin.setValue(int(defaults.get("pages", 2)))
        self.pages_spin.setSuffix(" 页")
        opts.addWidget(self.pages_spin, 0, 1)
        self.stop_on_hit = QCheckBox("命中即停止翻页")
        self.stop_on_hit.setChecked(bool(defaults.get("stop_on_hit", True)))
        opts.addWidget(self.stop_on_hit, 0, 2)
        self.headless = QCheckBox("后台运行（无头）")
        self.headless.setChecked(bool(defaults.get("headless", True)))
        opts.addWidget(self.headless, 1, 2)
        self.screenshot_all = QCheckBox("每一页都截图")
        self.screenshot_all.setChecked(bool(defaults.get("screenshot_all", False)))
        opts.addWidget(self.screenshot_all, 1, 0, 1, 2)
        opts.addWidget(QLabel("翻页间隔"), 2, 0)
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.5, 30.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setValue(float(defaults.get("delay", 2.0)))
        self.delay_spin.setSuffix(" 秒")
        opts.addWidget(self.delay_spin, 2, 1)
        lay.addWidget(opts_box)

        proxy_box = QGroupBox("代理设置（谷歌建议配置）")
        proxy_grid = QGridLayout(proxy_box)
        proxy_grid.setContentsMargins(12, 14, 12, 10)
        proxy_grid.setHorizontalSpacing(8)
        proxy_grid.setVerticalSpacing(6)
        proxy_grid.setColumnStretch(1, 1)
        self.proxy_edits: dict[str, QLineEdit] = {}
        self.proxy_status: dict[str, QLabel] = {}
        self.proxy_buttons: dict[str, QPushButton] = {}
        for row, name in enumerate(ENGINE_ORDER):
            proxy_grid.addWidget(QLabel(ENGINE_LABEL[name]), row, 0)
            edit = QLineEdit(
                str((defaults.get("proxies") or {}).get(name, ""))
                or str(self._last_good.get(name, ""))
            )
            edit.setPlaceholderText("http://127.0.0.1:7890" if name == "google" else "可选")
            self.proxy_edits[name] = edit
            proxy_grid.addWidget(edit, row, 1)
            test = ghost_button("测试")
            test.setFixedWidth(56)
            test.clicked.connect(lambda _=False, n=name: self._test_proxy(n))
            self.proxy_buttons[name] = test
            proxy_grid.addWidget(test, row, 2)
            status = QLabel("")
            status.setObjectName("Muted")
            status.setMinimumWidth(170)
            self.proxy_status[name] = status
            proxy_grid.addWidget(status, row, 3)
        hint = QLabel("只接受 HTTP / HTTPS 代理；请先启动 v2rayN、Clash 等客户端提供本地端口。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        proxy_grid.addWidget(hint, len(ENGINE_ORDER), 0, 1, 4)
        lay.addWidget(proxy_box)

        out_box = QGroupBox("输出")
        out_lay = QHBoxLayout(out_box)
        out_lay.setContentsMargins(12, 14, 12, 10)
        self.outdir_edit = QLineEdit(str(defaults.get("outdir") or default_outdir()))
        browse = ghost_button("选择")
        browse.clicked.connect(self._choose_outdir)
        out_lay.addWidget(self.outdir_edit, 1)
        out_lay.addWidget(browse)
        lay.addWidget(out_box)

        note = QLabel(f"浏览器：{browser_summary()}")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = ghost_button("取消")
        cancel.clicked.connect(self.reject)
        start = primary_button("开始查询")
        start.clicked.connect(self._accept)
        footer.addWidget(cancel)
        footer.addWidget(start)
        lay.addLayout(footer)

    def _test_proxy(self, engine: str) -> None:
        proxy = self.proxy_edits[engine].text().strip()
        if not proxy:
            self.proxy_status[engine].setText("先填写代理地址")
            self.proxy_status[engine].setStyleSheet("font-size:10px;color:#B4770B;")
            return
        self.proxy_buttons[engine].setEnabled(False)
        self.proxy_status[engine].setText("测试中…")
        self.proxy_status[engine].setStyleSheet("font-size:10px;color:#667085;")
        worker = ProxyTestThread(engine, proxy)
        _ACTIVE_PROXY_TESTS.add(worker)
        worker.result.connect(self._on_proxy_result)
        worker.finished.connect(lambda w=worker: _ACTIVE_PROXY_TESTS.discard(w))
        worker.start()

    def _on_proxy_result(self, engine: str, ok: bool, message: str) -> None:
        if ok:
            proxy = self.proxy_edits[engine].text().strip()
            self._last_good[engine] = proxy
            remember_good_proxy(self.settings, engine, proxy)
            message += " · 已记住"
        self.proxy_status[engine].setText(message)
        self.proxy_status[engine].setToolTip(message)
        self.proxy_status[engine].setStyleSheet(
            "font-size:10px;color:#1D8F66;" if ok else "font-size:10px;color:#C4453D;"
        )
        self.proxy_buttons[engine].setEnabled(True)

    def _choose_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.outdir_edit.text())
        if d:
            self.outdir_edit.setText(d)

    def _accept(self) -> None:
        if not any(cb.isChecked() for cb in self.engine_checks.values()):
            QMessageBox.warning(self, "请选择引擎", "至少选择一个搜索引擎。")
            return
        if not self.outdir_edit.text().strip():
            QMessageBox.warning(self, "输出目录", "请选择输出目录。")
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        return {
            "engines": {n: self.engine_checks[n].isChecked() for n in ENGINE_ORDER},
            "proxies": {n: self.proxy_edits[n].text().strip() for n in ENGINE_ORDER},
            "last_good_proxies": dict(self._last_good),
            "pages": self.pages_spin.value(),
            "headless": self.headless.isChecked(),
            "stop_on_hit": self.stop_on_hit.isChecked(),
            "screenshot_all": self.screenshot_all.isChecked(),
            "outdir": self.outdir_edit.text().strip() or str(default_outdir()),
            "delay": self.delay_spin.value(),
        }


class AboutDialog(QDialog):
    """关于窗口：作者、GitHub、版本和版权。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于{APP_NAME}")
        self.setWindowIcon(QApplication.windowIcon())
        self.setMinimumWidth(500)
        self.setMaximumWidth(620)
        self.setStyleSheet("QDialog{background:#F3F5F8;}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(12)

        card = QWidget()
        card.setObjectName("Panel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(22, 20, 22, 18)
        card_lay.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        icon = QLabel()
        icon.setFixedSize(68, 68)
        icon.setAlignment(Qt.AlignCenter)
        pixmap = QApplication.windowIcon().pixmap(68, 68)
        if pixmap.isNull():
            icon.setText("收")
            icon.setStyleSheet(
                "background:#F4A621;color:#FFFFFF;border-radius:19px;"
                "font-size:30px;font-weight:900;"
            )
        else:
            icon.setPixmap(pixmap)
        header.addWidget(icon)

        head_text = QVBoxLayout()
        head_text.setSpacing(3)
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size:22px;font-weight:900;color:#232B3E;")
        subtitle = QLabel(f"多品牌关键词收录查询 · v{APP_VERSION}")
        subtitle.setStyleSheet("font-size:11px;color:#8A94A6;")
        head_text.addWidget(title)
        head_text.addWidget(subtitle)
        head_text.addStretch(1)
        header.addLayout(head_text, 1)
        card_lay.addLayout(header)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#EEF1F5;")
        card_lay.addWidget(line)

        fields = QGridLayout()
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(10)
        fields.setColumnStretch(1, 1)

        def add_row(row: int, label: str, value: str, rich: bool = False) -> None:
            key = QLabel(label)
            key.setStyleSheet("font-size:11px;font-weight:700;color:#667085;")
            val = QLabel(value)
            val.setWordWrap(True)
            val.setStyleSheet("font-size:12px;color:#344054;")
            if rich:
                val.setTextFormat(Qt.RichText)
                val.setOpenExternalLinks(True)
                val.setStyleSheet("font-size:12px;color:#344054;")
            fields.addWidget(key, row, 0)
            fields.addWidget(val, row, 1)

        link_style = "font-size:12px;color:#B4770B;text-decoration:none;"
        add_row(0, "作者", APP_AUTHOR)
        add_row(1, "GitHub", f'<a href="{APP_GITHUB_URL}" style="{link_style}">{APP_GITHUB_HANDLE}</a>', True)
        add_row(2, "地址", f'<a href="{APP_GITHUB_URL}" style="{link_style}">{APP_GITHUB_URL}</a>', True)
        add_row(3, "版本", f"v{APP_VERSION}")
        add_row(4, "版权", APP_COPYRIGHT)
        add_row(5, "运行日志", "%LOCALAPPDATA%\\IndexChecker\\logs")
        card_lay.addLayout(fields)

        note = QLabel("本地运行 · 关键词不上传 · 报告可追溯")
        note.setStyleSheet("font-size:10px;color:#98A2B3;")
        card_lay.addWidget(note)

        lay.addWidget(card)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = primary_button("关闭")
        close.setFixedWidth(94)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        lay.addLayout(footer)
        self.adjustSize()

