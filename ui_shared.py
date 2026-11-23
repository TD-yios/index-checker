from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.browser import select_browser
from core.config import ENGINE_LABEL

APP_NAME = "收录查询工具"
APP_VERSION = "3.2.1"
APP_AUTHOR = "aromer"
APP_GITHUB_HANDLE = "@TD-yios"
APP_GITHUB_URL = "https://github.com/TD-yios/index-checker"
APP_COPYRIGHT = "© 2026 aromer · MIT License"
ENGINE_ORDER = ["baidu", "google", "bing", "toutiao"]
TYPE_ORDER = [("brand", "品牌专区"), ("card", "聚合卡片"), ("ad", "竞价广告"), ("organic", "自然排名")]
TYPE_LABEL = dict(TYPE_ORDER)
TYPE_COLOR = {"brand": "#FEF3C7", "card": "#DBEAFE", "ad": "#FEE2E2", "organic": "#DCFCE7"}


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "IndexChecker"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_outdir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "IndexChecker" / "outputs"
    else:
        base = Path(__file__).resolve().parent / "outputs"
    return base


def logs_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "IndexChecker" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


class RunLogger:
    """每次查询写一份 JSONL 运行日志，方便排查代理、验证码和进程问题。"""

    def __init__(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = logs_dir() / f"run_{stamp}.jsonl"

    def write(self, event: dict) -> None:
        try:
            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "event": event,
            }
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


class SingleInstance:
    """Windows 本地单实例：第二次启动时把已打开的窗口唤到前台。"""

    def __init__(self, key: str = "IndexChecker_SingleInstance_v3"):
        self.key = key
        self.server: QLocalServer | None = None

    def activate_existing(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if not socket.waitForConnected(500):
            return False
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True

    def listen(self, window) -> bool:
        self.server = QLocalServer()
        QLocalServer.removeServer(self.key)
        if not self.server.listen(self.key):
            return False
        self.server.newConnection.connect(lambda: self._handle_connection(window))
        return True

    def _handle_connection(self, window) -> None:
        if not self.server:
            return
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            if connection is None:
                continue
            connection.waitForReadyRead(300)
            try:
                connection.readAll()
            except Exception:
                pass
            window.showNormal()
            window.raise_()
            window.activateWindow()
            connection.disconnectFromServer()


def open_path(path: str | Path) -> None:
    if not path:
        return
    p = Path(path)
    if not p.exists():
        return
    try:
        os.startfile(str(p))
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def default_query_settings() -> dict[str, Any]:
    return {
        "engines": {"baidu": True, "google": False, "bing": True, "toutiao": False},
        "pages": 2,
        "proxies": {n: "" for n in ENGINE_ORDER},
        "last_good_proxies": {n: "" for n in ENGINE_ORDER},
        "headless": True,
        "stop_on_hit": True,
        "screenshot_all": False,
        "outdir": str(default_outdir()),
        "delay": 2.0,
    }


def load_query_settings(settings: QSettings) -> dict[str, Any]:
    data = default_query_settings()
    raw = settings.value("query_settings", "")
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                for key in ("pages", "headless", "stop_on_hit", "screenshot_all", "outdir", "delay"):
                    if key in loaded:
                        data[key] = loaded[key]
                for key in ("engines", "proxies", "last_good_proxies"):
                    if isinstance(loaded.get(key), dict):
                        data[key].update(loaded[key])
        except Exception:
            pass
    return data


def save_query_settings(settings: QSettings, data: dict[str, Any]) -> None:
    settings.setValue("query_settings", json.dumps(data, ensure_ascii=False))


def remember_good_proxy(settings: QSettings, engine: str, proxy: str) -> None:
    if not proxy:
        return
    data = load_query_settings(settings)
    data.setdefault("last_good_proxies", {})[engine] = proxy
    save_query_settings(settings, data)


def browser_summary() -> str:
    choice = select_browser()
    return choice.status_text()


def make_page_head(title: str, subtitle: str, eyebrow: str = "",
                   actions: list[QWidget] | None = None) -> QWidget:
    head = QWidget()
    h = QHBoxLayout(head)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(16)
    left = QVBoxLayout()
    left.setSpacing(5)
    if eyebrow:
        eyebrow_label = QLabel(eyebrow)
        eyebrow_label.setObjectName("Eyebrow")
        left.addWidget(eyebrow_label)
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    left.addWidget(title_label)
    sub = QLabel(subtitle)
    sub.setObjectName("PageSub")
    sub.setWordWrap(True)
    left.addWidget(sub)
    h.addLayout(left, 1)
    if actions:
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        for widget in actions:
            action_row.addWidget(widget)
        h.addLayout(action_row, 0)
    return head


def primary_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("PrimaryButton")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def ghost_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("GhostButton")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def danger_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("DangerButton")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def link_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("LinkButton")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class StatStrip(QWidget):
    """紧凑状态条：总数 + 四个状态 + 最近查询提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SummaryStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(62)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 0, 18, 0)
        h.setSpacing(16)

        self.total = QLabel("0")
        self.total.setObjectName("StatNumber")
        h.addWidget(self.total)
        total_label = QLabel("个关键词")
        total_label.setObjectName("StatLabel")
        h.addWidget(total_label)
        self.brand_label = QLabel("0 个品牌")
        self.brand_label.setObjectName("Muted")
        h.addWidget(self.brand_label)

        line = QWidget()
        line.setFixedWidth(1)
        line.setFixedHeight(28)
        line.setStyleSheet("background:#E9EDF3;")
        h.addWidget(line)

        self.items: dict[str, QLabel] = {}
        labels = [("pending", "待查", "#F4A621"), ("hit", "已命中", "#20AF7B"),
                  ("miss", "未命中", "#E05A54"), ("error", "异常", "#98A2B3")]
        for key, text, color in labels:
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(f"background:{color};border-radius:3px;")
            h.addWidget(dot)
            number = QLabel("0")
            number.setObjectName("StatNumberSmall")
            number.setStyleSheet("font-size:15px;font-weight:800;color:#344054;")
            h.addWidget(number)
            label = QLabel(text)
            label.setObjectName("StatLabel")
            h.addWidget(label)
            self.items[key] = number

        h.addStretch(1)
        self.note = QLabel("")
        self.note.setObjectName("Muted")
        h.addWidget(self.note)

    def set_values(self, total: int, brands: int, pending: int, hit: int, miss: int,
                   error: int, note: str = "") -> None:
        self.total.setText(str(total))
        self.brand_label.setText(f"{brands} 个品牌")
        self.items["pending"].setText(str(pending))
        self.items["hit"].setText(str(hit))
        self.items["miss"].setText(str(miss))
        self.items["error"].setText(str(error))
        self.note.setText(note)


class RunnerThread(QThread):
    event = Signal(dict)
    finished_code = Signal(int)

    def __init__(self, config_path: Path, stopfile: Path, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.stopfile = Path(stopfile)
        self.proc: subprocess.Popen | None = None

    def run(self) -> None:
        try:
            self.stopfile.unlink(missing_ok=True)
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--cli"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve().parent / "runner.py")]
        cmd += ["--config", str(self.config_path), "--stopfile", str(self.stopfile)]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=env, creationflags=flags, cwd=str(Path(__file__).resolve().parent),
            )
        except Exception as exc:
            self.event.emit({"type": "fatal", "message": f"无法启动查询进程：{exc}"})
            self.finished_code.emit(1)
            return

        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                event = {"type": "log", "level": "info", "message": line}
            self.event.emit(event)
        self.finished_code.emit(self.proc.wait())

    def request_stop(self) -> None:
        try:
            self.stopfile.parent.mkdir(parents=True, exist_ok=True)
            self.stopfile.write_text("1", encoding="utf-8")
        except Exception:
            pass

    def kill_tree(self) -> None:
        """停止查询进程及其浏览器子进程，避免关闭窗口后残留 Chrome。"""
        if not self.proc or self.proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return
            except Exception:
                pass
        try:
            self.proc.kill()
        except Exception:
            pass

    def stop(self) -> None:
        self.request_stop()
        if self.proc and self.proc.poll() is None:
            for _ in range(30):
                if self.proc.poll() is not None:
                    return
                self.msleep(200)
            try:
                self.proc.terminate()
            except Exception:
                pass


STYLE = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
QWidget { background: #F5F6F8; color: #1F2937; font-size: 13px; }
QLabel { background: transparent; }
QMainWindow { background: #F5F6F8; }
QWidget#SideBar { background: #FFFFFF; border-right: 1px solid #E5E9F0; }
QLabel#BrandName { font-size: 19px; font-weight: 800; color: #202738; }
QLabel#BrandSub { font-size: 12px; color: #98A2B3; font-weight: 700; }
QPushButton#NavButton {
    background: transparent; border: none; border-left: 3px solid transparent;
    text-align: left; padding: 0 0 0 17px; min-height: 40px;
    color: #667085; font-size: 13px; font-weight: 600;
}
QPushButton#NavButton:hover { background: #F8FAFD; color: #344054; }
QPushButton#NavButton:checked {
    background: #FFF6E6; color: #8A5A05; border-left: 3px solid #F4A621; font-weight: 700;
}
QLabel#PageTitle { font-size: 25px; font-weight: 800; color: #202738; }
QLabel#PageSub { font-size: 12px; color: #8A94A6; }
QLabel#Eyebrow { font-size: 12px; color: #B4770B; font-weight: 800; letter-spacing: 1px; }
QWidget#SummaryStrip { background: #FFFFFF; border: 1px solid #E5E9F0; border-radius: 10px; }
QLabel#StatNumber { font-size: 23px; font-weight: 800; color: #202738; }
QLabel#StatLabel { font-size: 12px; color: #667085; font-weight: 700; }
QLabel#Muted { font-size: 12px; color: #98A2B3; }
QWidget#Panel { background: #FFFFFF; border: 1px solid #E5E9F0; border-radius: 10px; }
QWidget#Toolbar { background: #FFFFFF; border-bottom: 1px solid #EEF1F5; }
QWidget#BatchBar { background: #FAFBFD; border-bottom: 1px solid #EEF1F5; }
QWidget#TabsBox { background: #F5F7FA; border-radius: 8px; }
QPushButton#FilterTab {
    background: transparent; border: none; border-radius: 6px; padding: 0 11px;
    min-height: 30px; color: #667085; font-size: 12px; font-weight: 700;
}
QPushButton#FilterTab:hover { color: #344054; }
QPushButton#FilterTab:checked { background: #FFFFFF; color: #202738; border: 1px solid #E1E6EF; }
QPushButton#PrimaryButton {
    background: #F4A621; color: #352405; border: 1px solid #F4A621; border-radius: 8px;
    padding: 0 14px; min-height: 33px; font-size: 12px; font-weight: 800;
}
QPushButton#PrimaryButton:hover { background: #FFB534; }
QPushButton#PrimaryButton:disabled { background: #F7D9A5; border-color: #F7D9A5; color: #8A6A32; }
QPushButton#GhostButton {
    background: #FFFFFF; color: #475467; border: 1px solid #E1E6EF; border-radius: 8px;
    padding: 0 13px; min-height: 33px; font-size: 12px; font-weight: 700;
}
QPushButton#GhostButton:hover { background: #F8FAFD; border-color: #D5DDEA; }
QPushButton#GhostButton:disabled { background: #FAFBFC; color: #B9C1CE; border-color: #E8ECF2; }
QPushButton#DangerButton {
    background: #FFFDFD; color: #C4453D; border: 1px solid #EFD3D0; border-radius: 8px;
    padding: 0 13px; min-height: 33px; font-size: 12px; font-weight: 700;
}
QPushButton#DangerButton:hover { background: #FFF7F6; }
QPushButton#DangerButton:disabled { background: #FAFBFC; color: #C9CFDA; border-color: #E8ECF2; }
QPushButton#LinkButton {
    background: transparent; border: none; color: #9A660F; font-size: 12px;
    font-weight: 800; padding: 0; text-align: left;
}
QPushButton#LinkButton:hover { color: #C07A0A; }
QPushButton#RowCheck {
    background: #FFFFFF; border: 1px solid #D8DEE9; border-radius: 4px;
    color: #5A3B00; font-size: 12px; font-weight: 800; padding: 0;
}
QPushButton#RowCheck:checked { background: #F4A621; border-color: #F4A621; }
QPushButton#RowPrimary {
    background: #FFF8EA; color: #9A660F; border: 1px solid #F0D6A5; border-radius: 5px;
    padding: 0 8px; min-height: 26px; font-size: 12px; font-weight: 800;
}
QPushButton#RowPrimary:hover { background: #FFF1D6; }
QPushButton#RowGhost {
    background: #FFFFFF; color: #667085; border: 1px solid #E5EAF2; border-radius: 5px;
    padding: 0 7px; min-height: 26px; font-size: 12px; font-weight: 700;
}
QPushButton#RowGhost:hover { background: #F8FAFD; }
QLabel#StatusHit { background: #EAF8F1; color: #1D8F66; border-radius: 4px; padding: 3px 8px; font-size: 12px; font-weight: 800; }
QLabel#StatusPending { background: #FFF4DE; color: #A96A07; border-radius: 4px; padding: 3px 8px; font-size: 12px; font-weight: 800; }
QLabel#StatusMiss { background: #FDECEC; color: #C24A45; border-radius: 4px; padding: 3px 8px; font-size: 12px; font-weight: 800; }
QLabel#StatusError { background: #FDECEC; color: #C24A45; border-radius: 4px; padding: 3px 8px; font-size: 12px; font-weight: 800; }
QLabel#StatusRunning { background: #EEF3FF; color: #3E68D8; border-radius: 4px; padding: 3px 8px; font-size: 12px; font-weight: 800; }
QLabel#TagBrand { background: #FFF4DE; color: #A96A07; border-radius: 3px; padding: 2px 5px; font-size: 12px; font-weight: 800; }
QLabel#TagCard { background: #EEF3FF; color: #3E68D8; border-radius: 3px; padding: 2px 5px; font-size: 12px; font-weight: 800; }
QLabel#TagAd { background: #FDECEC; color: #C24A45; border-radius: 3px; padding: 2px 5px; font-size: 12px; font-weight: 800; }
QLabel#TagOrganic { background: #EAF8F1; color: #1D8F66; border-radius: 3px; padding: 2px 5px; font-size: 12px; font-weight: 800; }
QLabel#TagGray { background: #F3F5F9; color: #8C95A6; border-radius: 3px; padding: 2px 5px; font-size: 12px; font-weight: 800; }
QWidget#BrandGroupHeader { background: #F6F8FB; border-top: 1px solid #E9EDF3; border-bottom: 1px solid #E9EDF3; }
QLabel#BrandGroupName { font-size: 13px; font-weight: 800; color: #252C3B; }
QLabel#GroupCount { background: #FFFFFF; color: #7C8799; border: 1px solid #E5EAF2; border-radius: 4px; padding: 2px 6px; font-size: 12px; font-weight: 700; }
QLabel#GroupUrls { font-size: 12px; color: #697586; }
QTableWidget { background: #FFFFFF; border: none; gridline-color: transparent; font-size: 12px; }
QTableWidget::item { border-bottom: 1px solid #F1F3F7; padding: 0 8px; }
QTableWidget::item:selected { background: #FFF9EB; color: #252C3B; }
QHeaderView::section {
    background: #FBFCFE; color: #7C8799; border: none; border-bottom: 1px solid #E9EDF3;
    padding: 0 8px; min-height: 38px; font-size: 12px; font-weight: 800;
}
QTableCornerButton::section { background: #FBFCFE; border: none; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF; border: 1px solid #DDE3ED; border-radius: 6px; padding: 5px 8px;
    selection-background-color: #FDE7BE; font-size: 12px;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #E7B457;
}
QCheckBox { font-size: 12px; color: #475467; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; }
QCheckBox::indicator:unchecked { border: 1px solid #D1D5DB; background: #FFFFFF; border-radius: 3px; }
QCheckBox::indicator:checked { border: 1px solid #F4A621; background: #F4A621; }
QGroupBox { background: #FFFFFF; border: 1px solid #E5E9F0; border-radius: 8px; margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 700; color: #344054; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; background: #FFFFFF; }
QPushButton { font-family: inherit; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; padding: 8px 15px; color: #667085; font-size: 12px; }
QTabBar::tab:selected { color: #202738; font-weight: 800; border-bottom: 2px solid #F4A621; }
QProgressBar { border: none; background: #E9EDF3; border-radius: 7px; text-align: center; color: #475467; font-size: 12px; }
QProgressBar::chunk { background: #F4A621; border-radius: 7px; }
QPlainTextEdit#Log { background: #111827; color: #D1D5DB; font-family: Consolas, "Microsoft YaHei UI"; font-size: 12px; border-radius: 6px; padding: 8px; }
QDialog { background: #F5F6F8; }
QWidget#DialogBody { background: #F5F6F8; }
QToolTip { background: #202738; color: #FFFFFF; border: none; padding: 5px 8px; }
QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: #F5F6F8; width: 8px; }
QMessageBox { background: #F5F6F8; }
"""
