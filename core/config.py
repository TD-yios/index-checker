from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ENGINE_DEFAULT_HOST = {
    "baidu": "www.baidu.com",
    "google": "www.google.com",
    "bing": "cn.bing.com",
    "toutiao": "so.toutiao.com",
}

ENGINE_LABEL = {"baidu": "百度", "google": "谷歌", "bing": "必应", "toutiao": "头条搜索"}


@dataclass
class JobConfig:
    keywords: list[str] = field(default_factory=list)
    target_domain: str = ""
    tasks: list[dict[str, Any]] = field(default_factory=list)
    engines: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "baidu": {"enabled": True, "proxy": ""},
            "google": {"enabled": False, "proxy": ""},
            "bing": {"enabled": True, "proxy": ""},
            "toutiao": {"enabled": False, "proxy": ""},
        }
    )
    max_pages: int = 3
    results_per_page: int = 10
    stop_on_hit: bool = True
    screenshot_on_hit: bool = True
    screenshot_all_pages: bool = False
    save_html: bool = False
    headless: bool = True
    wait_timeout: int = 25          # 单页加载等待上限（秒）
    captcha_wait: int = 90          # 可见模式下等待人工过验证的时长（秒）
    delay_min: float = 2.0
    delay_max: float = 4.0
    output_dir: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "JobConfig":
        cfg = JobConfig()
        cfg.keywords = [str(k).strip() for k in (d.get("keywords") or []) if str(k).strip()]
        cfg.target_domain = str(d.get("target_domain") or "").strip()
        cfg.tasks = []
        for item in (d.get("tasks") or []):
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            target_url = str(item.get("target_url") or "").strip()
            if not keyword or not target_url:
                continue
            cfg.tasks.append({
                "brand": str(item.get("brand") or "").strip(),
                "keyword": keyword,
                "target_url": target_url,
                "library_id": item.get("library_id"),
            })
        engines = d.get("engines") or {}
        merged: dict[str, dict[str, Any]] = {}
        for name in ("baidu", "google", "bing", "toutiao"):
            base = dict(cfg.engines[name])
            user = engines.get(name) or {}
            base.update({k: user[k] for k in ("enabled", "proxy") if k in user})
            merged[name] = base
        cfg.engines = merged
        for key in (
            "max_pages", "results_per_page", "wait_timeout", "captcha_wait",
        ):
            if d.get(key) is not None:
                setattr(cfg, key, int(d[key]))
        for key in (
            "stop_on_hit", "screenshot_on_hit", "screenshot_all_pages",
            "save_html", "headless",
        ):
            if d.get(key) is not None:
                setattr(cfg, key, bool(d[key]))
        for key in ("delay_min", "delay_max"):
            if d.get(key) is not None:
                setattr(cfg, key, float(d[key]))
        cfg.output_dir = str(d.get("output_dir") or "")
        return cfg

    def enabled_engines(self) -> list[str]:
        return [n for n in ("baidu", "google", "bing", "toutiao") if self.engines.get(n, {}).get("enabled")]

    def validate(self) -> list[str]:
        errs = []
        if self.tasks:
            for idx, item in enumerate(self.tasks, start=1):
                if not normalize_domain(item.get("target_url", "")):
                    errs.append(f"第 {idx} 个任务的目标 URL 无效")
            if not self.enabled_engines():
                errs.append("请至少选择一个搜索引擎")
            if self.max_pages < 1:
                errs.append("翻页次数至少为 1")
            return errs
        if not self.keywords:
            errs.append("请至少填写一个关键词")
        if not self.target_domain:
            errs.append("请填写目标域名")
        if not self.enabled_engines():
            errs.append("请至少选择一个搜索引擎")
        if self.max_pages < 1:
            errs.append("翻页次数至少为 1")
        return errs


def normalize_domain(raw: str) -> str:
    """把用户输入的域名/网址统一成 host，去掉协议、路径、www. 前缀。"""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    s = s.split("@")[-1]
    if ":" in s:
        s = s.split(":", 1)[0]
    while s.startswith("www."):
        s = s[4:]
    s = s.strip(".")
    return s


def host_matches(host: str, target: str) -> bool:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host == target or host.endswith("." + target)
