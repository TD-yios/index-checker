from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _app_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _chrome_dirs() -> list[Path]:
    return [
        Path(r"C:\Program Files\Google\Chrome\Application"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application"),
        Path.home() / r"AppData\Local\Google\Chrome\Application",
    ]


def _chrome_registry_version() -> str:
    import winreg

    paths = [
        (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome\BLBeacon"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon"),
    ]
    for hive, sub in paths:
        try:
            with winreg.OpenKey(hive, sub) as key:
                version, _ = winreg.QueryValueEx(key, "version")
                return str(version)
        except Exception:
            continue
    return ""


def installed_chrome() -> tuple[Path, str] | None:
    for base in _chrome_dirs():
        exe = base / "chrome.exe"
        if exe.exists():
            version = _chrome_registry_version()
            if not version:
                for child in base.iterdir():
                    if child.is_dir() and child.name[:1].isdigit():
                        version = child.name
                        break
            return exe, version
    return None


def installed_edge() -> tuple[Path, str] | None:
    bases = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application"),
        Path(r"C:\Program Files\Microsoft\Edge\Application"),
    ]
    for base in bases:
        exe = base / "msedge.exe"
        if exe.exists():
            version = ""
            for child in base.iterdir():
                if child.is_dir() and child.name[:1].isdigit():
                    version = child.name
                    break
            return exe, version
    return None


def _browser_candidates() -> list[Path]:
    bases: list[Path] = []
    env = os.environ.get("INDEX_CHECKER_BROWSER_DIR", "").strip()
    if env:
        bases.append(Path(env))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(Path(meipass) / "browser" / "chrome-win64")
        bases.append(Path(meipass) / "browser")
    app = _app_base()
    bases += [
        app / "browser" / "chrome-win64",
        app / "browser",
        app / "vendor" / "chrome-win64",
    ]
    return bases


def bundled_chrome() -> tuple[Path, str] | None:
    for base in _browser_candidates():
        exe = base / "chrome.exe"
        if not exe.exists():
            nested = base / "chrome-win64" / "chrome.exe"
            if nested.exists():
                exe, base = nested, nested.parent
        if not exe.exists():
            continue
        version = ""
        for vf in (base / "version.txt", base.parent / "version.txt"):
            try:
                if vf.exists():
                    version = vf.read_text(encoding="utf-8").strip()
                    break
            except Exception:
                pass
        return exe, version
    return None


@dataclass(frozen=True)
class BrowserChoice:
    mode: str                 # chrome / bundled / edge / playwright
    executable: Path | None
    channel: str | None
    version: str
    profile_key: str
    bundled_version: str = ""
    installed_version: str = ""

    @property
    def major(self) -> str:
        return self.version.split(".")[0] if self.version else ""

    def status_text(self) -> str:
        if self.mode == "chrome":
            text = f"本机 Chrome {self.major or ''}".rstrip()
            if self.bundled_version:
                text += f" · 内置 {self.bundled_version.split('.')[0]} 备用"
            return text
        if self.mode == "bundled":
            return f"内置 Chrome {self.major or ''}（免安装）".replace("  ", " ")
        if self.mode == "edge":
            return "系统 Edge（未找到 Chrome）"
        return "Playwright 内核（未检测到内置浏览器）"


def select_browser() -> BrowserChoice:
    bundled = bundled_chrome()
    bundled_version = bundled[1] if bundled else ""

    # 显式指定内置浏览器目录时优先使用，便于离线机/打包验证
    if os.environ.get("INDEX_CHECKER_BROWSER_DIR", "").strip() and bundled:
        exe, version = bundled
        return BrowserChoice("bundled", exe, None, version, "bundled",
                             bundled_version=version)

    chrome = installed_chrome()
    if chrome:
        exe, version = chrome
        return BrowserChoice("chrome", exe, "chrome", version, "chrome",
                             bundled_version=bundled_version, installed_version=version)
    if bundled:
        exe, version = bundled
        return BrowserChoice("bundled", exe, None, version, "bundled",
                             bundled_version=version)
    edge = installed_edge()
    if edge:
        exe, version = edge
        return BrowserChoice("edge", exe, "msedge", version, "edge",
                             bundled_version="", installed_version=version)
    return BrowserChoice("playwright", None, None, "", "chromium")


def browser_available(choice: BrowserChoice) -> bool:
    if choice.mode == "playwright":
        return False
    return bool(choice.executable and choice.executable.exists())
