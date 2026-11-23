from __future__ import annotations

import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .browser import select_browser
from .config import ENGINE_LABEL, JobConfig, normalize_domain
from .engines import KIND_LABEL, UA, ResultItem, calc_global_rank, decode_wrapped_url, get_engine, judge_hit
from .report import write_reports

Emit = Callable[[dict[str, Any]], None]


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "IndexChecker"
    p.mkdir(parents=True, exist_ok=True)
    return p

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


MARK_HITS_JS = r"""
(hits) => {
  document.querySelectorAll('.ic-hit-mark, .ic-hit-label').forEach((el) => el.remove());
  let count = 0;
  const scrollX = window.scrollX || window.pageXOffset || 0;
  const scrollY = window.scrollY || window.pageYOffset || 0;
  hits.forEach((h) => {
    if (!h.id) return;
    const el = document.querySelector(`[data-ic-hit="${h.id}"]`);
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const x = Math.max(0, r.left + scrollX - 3);
    const y = Math.max(0, r.top + scrollY - 3);
    const box = document.createElement('div');
    box.className = 'ic-hit-mark';
    box.style.position = 'absolute';
    box.style.left = x + 'px';
    box.style.top = y + 'px';
    box.style.width = Math.max(2, r.width + 6) + 'px';
    box.style.height = Math.max(2, r.height + 6) + 'px';
    box.style.border = '3px solid ' + h.color;
    box.style.borderRadius = '5px';
    box.style.boxSizing = 'border-box';
    box.style.zIndex = '2147483646';
    box.style.pointerEvents = 'none';
    document.body.appendChild(box);

    const label = document.createElement('div');
    label.className = 'ic-hit-label';
    label.textContent = h.label;
    label.style.position = 'absolute';
    label.style.left = Math.max(0, r.left + scrollX - 3) + 'px';
    label.style.top = Math.max(0, r.top + scrollY - 27) + 'px';
    label.style.zIndex = '2147483647';
    label.style.padding = '3px 7px';
    label.style.borderRadius = '4px';
    label.style.background = h.color;
    label.style.color = '#ffffff';
    label.style.font = 'bold 15px/1.2 "Microsoft YaHei", Arial, sans-serif';
    label.style.whiteSpace = 'nowrap';
    label.style.boxShadow = '0 1px 4px rgba(0,0,0,.28)';
    label.style.pointerEvents = 'none';
    document.body.appendChild(label);
    count += 1;
  });
  return count;
}
"""


def _ua_for(version: str) -> str:
    major = version.split(".")[0] if version else ""
    ver = f"{major}.0.0.0" if major else "131.0.0.0"
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{ver} Safari/537.36"
    )


def safe_name(text: str, limit: int = 40) -> str:
    s = _BAD_CHARS.sub("_", text).strip(" ._")
    return (s[:limit] or "keyword")


class BrowserSession:
    """单个搜索引擎的浏览器会话（独立 cookie / 代理 / 可见性）。"""

    def __init__(self, engine_name: str, cfg: JobConfig, emit: Emit):
        self.engine = get_engine(engine_name)
        self.name = engine_name
        self.cfg = cfg
        self.emit = emit
        self._pw = None
        self.ctx = None
        self.page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        proxy = (self.cfg.engines.get(self.name) or {}).get("proxy") or ""
        if self.name == "google" and not proxy and self.cfg.headless:
            self.emit({"type": "log", "level": "warn", "message": "谷歌未配置代理，若网络不通将跳过该引擎。"})

        choice = select_browser()
        if choice.mode == "bundled":
            self.emit({"type": "log", "level": "info",
                       "message": f"{ENGINE_LABEL[self.name]} 使用内置 Chrome {choice.major}（免安装）"})
        elif choice.mode == "playwright":
            self.emit({"type": "log", "level": "warn",
                       "message": "未检测到本机 Chrome / Edge 和内置浏览器，将尝试 Playwright Chromium"})
        profile = data_dir() / "profiles" / choice.profile_key / self.name
        profile.mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
        launch_opts: dict[str, Any] = dict(
            user_data_dir=str(profile),
            headless=self.cfg.headless,
            proxy={"server": proxy} if proxy else None,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--lang=zh-CN",
            ],
        )
        if choice.channel:
            launch_opts["channel"] = choice.channel
        elif choice.executable:
            launch_opts["executable_path"] = str(choice.executable)
        launch_opts["user_agent"] = _ua_for(choice.version)
        self.ctx = self._pw.chromium.launch_persistent_context(**launch_opts)
        try:
            self.ctx.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                window.chrome = window.chrome || {runtime: {}};
                """
            )
        except Exception:
            pass
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(self.cfg.wait_timeout * 1000)

    # ---------- helpers ----------
    def dismiss_overlays(self) -> None:
        texts = ["全部接受", "接受所有", "接受", "同意并继续", "同意", "Accept all", "Accept", "我知道了"]
        for text in texts:
            try:
                btn = self.page.get_by_role("button", name=text, exact=False)
                if btn.count() > 0:
                    btn.first.click(timeout=1500)
                    self.page.wait_for_timeout(300)
            except Exception:
                continue

    def navigate_search(self, keyword: str, page_no: int, per_page: int) -> str:
        """打开指定搜索结果页。头条的翻页依赖首屏 search_id，改用“下一页”链接。"""
        if self.name == "toutiao" and page_no > 1:
            next_link = self.page.get_by_text("下一页", exact=True)
            if next_link.count() == 0:
                return ""
            next_link.first.click(timeout=self.cfg.wait_timeout * 1000)
            # 头条翻页是前端请求，URL 会在点击后带上 search_id。
            self.page.wait_for_timeout(1200)
            return self.page.url

        url = self.engine.build_url(keyword, page_no, per_page)
        self.page.goto(url, timeout=self.cfg.wait_timeout * 1000, wait_until="domcontentloaded")
        return self.page.url

    def resolve_url(self, url: str) -> str:
        """解析百度等跳转链接的真实落地地址（不跟随完整页面内容）。"""
        if not url:
            return ""
        try:
            resp = self.ctx.request.get(url, max_redirects=0, timeout=8000)
            loc = resp.headers.get("location") or resp.headers.get("Location")
            if loc:
                return loc if loc.startswith("http") else "https://" + loc.lstrip("/")
            return resp.url or url
        except Exception:
            return ""

    def enrich(self, items: list[ResultItem]) -> None:
        for item in items:
            if item.real_url and "baidu.com/link" not in item.real_url:
                continue
            if item.href and "baidu.com/link" in item.href:
                resolved = self.resolve_url(item.href)
                if resolved:
                    item.real_url = resolved
            elif not item.real_url:
                item.real_url = decode_wrapped_url(item.href, self.name)

    def blocked_reason(self, url: str) -> str:
        try:
            body = self.page.inner_text("body")[:2000]
        except Exception:
            body = ""
        return self.engine.blocked_reason(url, body)

    def mark_hits(self, hits: list[dict[str, Any]]) -> int:
        if not hits:
            return 0
        payload = []
        for h in hits:
            global_rank = h.get("global_rank")
            if h.get("kind") == "organic" and global_rank:
                label = f"#{global_rank} 自然排名"
                color = "#15803D"
            elif h.get("kind") == "brand":
                label, color = "品牌专区", "#B45309"
            elif h.get("kind") == "card":
                label, color = "聚合卡片", "#1D4ED8"
            elif h.get("kind") == "ad":
                label, color = "竞价广告", "#B91C1C"
            else:
                label, color = str(h.get("type") or "命中"), "#475467"
            payload.append({"id": h.get("hit_id") or "", "label": label, "color": color})
        try:
            return int(self.page.evaluate(MARK_HITS_JS, payload) or 0)
        except Exception:
            return 0

    def clear_hit_marks(self) -> None:
        try:
            self.page.evaluate(
                "() => document.querySelectorAll('.ic-hit-mark, .ic-hit-label')"
                ".forEach((el) => el.remove())"
            )
        except Exception:
            pass

    def capture(self, path: Path, hits: Optional[list[dict[str, Any]]] = None) -> Optional[str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if hits:
                self.mark_hits(hits)
            self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            try:
                self.page.screenshot(path=str(path), full_page=False)
                return str(path)
            except Exception:
                return None
        finally:
            self.clear_hit_marks()

    def close(self) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def _wait_manual_verify(sess: BrowserSession, cfg: JobConfig) -> bool:
    """可见模式下等待用户在浏览器里通过验证码。"""
    if cfg.headless or cfg.captcha_wait <= 0:
        return False
    sess.emit({
        "type": "log",
        "level": "warn",
        "message": "检测到安全验证，请在弹出的浏览器窗口中完成验证（最多等待 %d 秒）" % cfg.captcha_wait,
    })
    deadline = time.time() + cfg.captcha_wait
    while time.time() < deadline:
        sess.page.wait_for_timeout(1500)
        if sess.page.query_selector(sess.engine.wait_selector):
            try:
                body = sess.page.inner_text("body")[:1500]
            except Exception:
                body = ""
            if not sess.engine.blocked_reason(sess.page.url, body):
                return True
    return False


def _job_tasks(cfg: JobConfig) -> list[dict[str, Any]]:
    if cfg.tasks:
        tasks: list[dict[str, Any]] = []
        for item in cfg.tasks:
            url = str(item.get("target_url") or "").strip()
            tasks.append({
                "brand": str(item.get("brand") or "").strip(),
                "keyword": str(item.get("keyword") or "").strip(),
                "target_url": url,
                "target_domain": normalize_domain(url),
                "library_id": item.get("library_id"),
            })
        return [t for t in tasks if t["keyword"] and t["target_domain"]]
    target = normalize_domain(cfg.target_domain)
    return [
        {"brand": "", "keyword": kw, "target_url": cfg.target_domain,
         "target_domain": target, "library_id": None}
        for kw in cfg.keywords if kw and target
    ]


def _hit_summary(type_stats: dict[str, dict[str, Any]]) -> str:
    labels = {"brand": "品牌", "card": "卡片", "ad": "竞价", "organic": "自然"}
    parts = [f"{labels[k]} {type_stats[k]['count']}" for k in ("brand", "card", "ad", "organic")
             if type_stats[k]["count"]]
    return " · ".join(parts) if parts else "0 命中"


def run_job(cfg: JobConfig, emit: Emit, stop_flag: Optional[Callable[[], bool]] = None,
            outdir: Optional[Path] = None) -> dict[str, Any]:
    tasks = _job_tasks(cfg)
    targets = sorted({t["target_domain"] for t in tasks if t["target_domain"]})
    brands = sorted({t["brand"] for t in tasks if t["brand"]})
    if len(targets) == 1:
        target_label = targets[0]
    elif len(brands) == 1:
        target_label = f"{brands[0]}（{len(targets)} 个目标）"
    else:
        target_label = f"多品牌（{len(targets)} 个目标）"
    if outdir is None and cfg.output_dir:
        outdir = Path(cfg.output_dir)
    if outdir is None:
        base = (data_dir() / "outputs") if getattr(sys, "frozen", False) else (
            Path(__file__).resolve().parent.parent / "outputs")
        outdir = base / datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cfg.output_dir = str(outdir)

    engines = cfg.enabled_engines()
    total_tasks = len(engines) * len(tasks)
    done = 0
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    emit({"type": "start", "total": total_tasks, "outdir": str(outdir),
          "target": target_label, "targets": targets, "brands": brands,
          "engines": engines, "tasks": len(tasks)})

    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    hit_rows: list[dict[str, Any]] = []
    stats = {"tasks": 0, "hit_tasks": 0, "pages": 0, "hits": 0}

    for engine_name in engines:
        if stop_flag and stop_flag():
            break
        label = ENGINE_LABEL[engine_name]
        sess = BrowserSession(engine_name, cfg, emit)
        try:
            emit({"type": "log", "level": "info", "message": f"[{label}] 启动浏览器…"})
            sess.start()
        except Exception as e:
            emit({"type": "log", "level": "error", "message": f"[{label}] 浏览器启动失败：{e}"})
            for task in tasks:
                summary_rows.append({
                    "时间": started_at, "品牌": task["brand"], "关键词": task["keyword"],
                    "目标URL": task["target_url"], "搜索引擎": label, "是否命中": "否",
                    "品牌专区数": 0, "品牌首现页": "", "聚合卡片数": 0, "卡片首现页": "",
                    "竞价广告数": 0, "广告首现页": "", "自然排名数": 0, "自然首现页": "",
                    "自然首现页内位": "", "自然首现全局位": "", "命中URL": "", "命中总数": 0, "检查页数": 0,
                    "状态": "浏览器启动失败",
                })
                emit({"type": "task_done", "library_id": task.get("library_id"),
                      "brand": task["brand"], "keyword": task["keyword"],
                      "target_url": task["target_url"], "engine": engine_name,
                      "engine_label": label, "status": "error", "summary": "浏览器启动失败",
                      "hit_count": 0})
                done += 1
                emit({"type": "progress", "done": done, "total": total_tasks})
            continue

        try:
            for task in tasks:
                if stop_flag and stop_flag():
                    break
                kw = task["keyword"]
                brand = task["brand"]
                target = task["target_domain"]
                target_url = task["target_url"]
                library_id = task.get("library_id")
                hit_list: list[dict[str, Any]] = []
                first_page = None
                first_rank: Any = None
                first_url = ""
                hit_types: list[str] = []
                type_stats = {
                    k: {"count": 0, "first_page": None, "first_rank": "",
                        "first_global_rank": "", "url": ""}
                    for k in ("brand", "card", "ad", "organic")
                }
                pages_checked = 0
                task_status = "正常"
                organic_before = 0

                for page_no in range(1, cfg.max_pages + 1):
                    if stop_flag and stop_flag():
                        break
                    url = sess.engine.build_url(kw, page_no, cfg.results_per_page)
                    emit({"type": "log", "level": "info",
                          "message": f"[{label}] {kw} · 第 {page_no} 页"})
                    status = "ok"
                    message = ""
                    items: list[ResultItem] = []
                    organic_on_page = 0
                    shot = None
                    try:
                        navigated = sess.navigate_search(kw, page_no, cfg.results_per_page)
                        url = sess.page.url
                        if not navigated:
                            status = "no_results"
                            message = "已到末页（没有找到“下一页”入口）"
                        else:
                            try:
                                sess.page.wait_for_selector(sess.engine.wait_selector,
                                                            timeout=cfg.wait_timeout * 1000 // 2)
                            except Exception:
                                pass
                            sess.page.wait_for_timeout(1200)
                            sess.dismiss_overlays()

                            reason = sess.blocked_reason(url)
                            if reason:
                                if _wait_manual_verify(sess, cfg):
                                    reason = ""
                                else:
                                    status = "captcha"
                                    message = reason
                            if status == "ok":
                                # 头条页首热榜/聚合卡片可能比自然结果先渲染，
                                # 第一次只看到非自然卡片时再等一次，避免慢网误报无结果。
                                for attempt in range(2):
                                    raw = sess.page.evaluate(sess.engine.extract_js()) or []
                                    items = sess.engine.parse_items(raw)
                                    sess.enrich(items)
                                    if (sess.name == "toutiao" and attempt == 0
                                            and not any(i.kind == "organic" for i in items)):
                                        sess.page.wait_for_timeout(1500)
                                        continue
                                    break
                                organic_on_page = sum(1 for i in items if i.kind == "organic")
                                if not items:
                                    status = "no_results"
                                    message = "该页未解析到自然结果（可能已到末页或页面结构变化）"
                    except Exception as e:
                        status = "network_error" if "timeout" in str(e).lower() else "error"
                        message = str(e).split("\n")[0][:200]

                    pages_checked += 1
                    stats["pages"] += 1

                    hits_this_page = []
                    if items:
                        for item in items:
                            matched, hit_url = judge_hit(item, target, engine_name)
                            if matched:
                                global_rank = None
                                if item.kind == "organic" and item.rank:
                                    global_rank = calc_global_rank(
                                        page_no, item.rank, cfg.results_per_page,
                                        previous_organic=organic_before,
                                    )
                                hits_this_page.append({
                                    "rank": item.rank,
                                    "page": page_no,
                                    "pos_in_page": item.rank if item.kind == "organic" else "",
                                    "global_rank": global_rank,
                                    "pos": item.pos,
                                    "kind": item.kind,
                                    "type": KIND_LABEL.get(item.kind, item.kind),
                                    "title": item.title,
                                    "url": hit_url or item.real_url or item.href,
                                    "display": item.display,
                                    "hit_id": item.hit_id,
                                })

                    fname_base = safe_name(f"{brand}_{kw}" if brand and brand != kw else kw)
                    need_shot = bool(hits_this_page) and cfg.screenshot_on_hit or cfg.screenshot_all_pages or status in ("captcha", "error", "network_error")
                    if need_shot:
                        fname = f"{fname_base}_{engine_name}_p{page_no}"
                        if status in ("captcha", "error", "network_error"):
                            fname += "_" + status
                        shot = sess.capture(outdir / engine_name / f"{fname}.png", hits_this_page)

                    if cfg.save_html and (hits_this_page or status != "ok"):
                        try:
                            html_path = outdir / engine_name / f"{fname_base}_{engine_name}_p{page_no}.html"
                            html_path.write_text(sess.page.content(), encoding="utf-8")
                        except Exception:
                            pass

                    if hits_this_page:
                        stats["hits"] += len(hits_this_page)
                        hit_types.extend(h["type"] for h in hits_this_page)
                        if first_page is None:
                            first_page = page_no
                            first_hit = hits_this_page[0]
                            first_rank = (first_hit["global_rank"]
                                          if first_hit["kind"] == "organic" else first_hit["type"])
                            first_url = first_hit["url"]
                        for h in hits_this_page:
                            st = type_stats[h["kind"]]
                            st["count"] += 1
                            if st["first_page"] is None:
                                st["first_page"] = page_no
                                st["first_rank"] = h["rank"] if h["kind"] == "organic" else ""
                                st["first_global_rank"] = h["global_rank"] if h["kind"] == "organic" else ""
                                st["url"] = h["url"]
                            hit_rows.append({
                                "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "品牌": brand,
                                "关键词": kw,
                                "目标URL": target_url,
                                "搜索引擎": label,
                                "页码": page_no,
                                "页内位次": h["pos_in_page"],
                                "全局排名": h["global_rank"] if h["kind"] == "organic" else "",
                                "类型": h["type"],
                                "标题": h["title"],
                                "URL": h["url"],
                                "截图": shot or "",
                            })
                        hit_list.extend(hits_this_page)

                    detail_rows.append({
                        "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "品牌": brand,
                        "关键词": kw,
                        "目标URL": target_url,
                        "搜索引擎": label,
                        "页码": page_no,
                        "状态": {"ok": "正常", "no_results": "无结果/末页", "captcha": "安全验证",
                                 "network_error": "网络超时", "error": "页面异常"}.get(status, status),
                        "命中数": len(hits_this_page),
                        "命中类型": "、".join(sorted({h["type"] for h in hits_this_page})) or "",
                        "命中排位": "、".join(
                            (f"自然#{h['global_rank']}" if h["kind"] == "organic" else h["type"])
                            for h in hits_this_page
                        ),
                        "命中URL": "\n".join(h["url"] for h in hits_this_page),
                        "命中标题": "\n".join(h["title"] for h in hits_this_page),
                        "截图": shot or "",
                        "搜索URL": url,
                        "备注": message,
                    })

                    emit({"type": "page", "keyword": kw, "brand": brand, "target_url": target_url,
                          "target_domain": target, "library_id": library_id,
                          "engine": engine_name, "engine_label": label,
                          "page": page_no, "status": status, "message": message,
                          "hits": hits_this_page, "screenshot": shot, "search_url": url})

                    if status in ("captcha", "network_error", "error"):
                        task_status = {"captcha": "安全验证", "network_error": "网络超时"}.get(status, "页面异常")
                        break
                    if hits_this_page and cfg.stop_on_hit and any(h["kind"] == "organic" for h in hits_this_page):
                        break
                    if status == "no_results" and page_no >= 1:
                        break
                    organic_before += organic_on_page
                    time.sleep(random.uniform(cfg.delay_min, cfg.delay_max))

                stats["tasks"] += 1
                if hit_list:
                    stats["hit_tasks"] += 1
                summary_rows.append({
                    "时间": started_at,
                    "品牌": brand,
                    "关键词": kw,
                    "目标URL": target_url,
                    "搜索引擎": label,
                    "是否命中": "是" if hit_list else "否",
                    "品牌专区数": type_stats["brand"]["count"],
                    "品牌首现页": type_stats["brand"]["first_page"] or "",
                    "聚合卡片数": type_stats["card"]["count"],
                    "卡片首现页": type_stats["card"]["first_page"] or "",
                    "竞价广告数": type_stats["ad"]["count"],
                    "广告首现页": type_stats["ad"]["first_page"] or "",
                    "自然排名数": type_stats["organic"]["count"],
                    "自然首现页": type_stats["organic"]["first_page"] or "",
                    "自然首现页内位": type_stats["organic"]["first_rank"] or "",
                    "自然首现全局位": type_stats["organic"]["first_global_rank"] or "",
                    "命中URL": type_stats["organic"]["url"] or first_url,
                    "命中总数": len(hit_list),
                    "检查页数": pages_checked,
                    "状态": task_status,
                })
                done += 1
                result_status = "error" if task_status != "正常" else ("hit" if hit_list else "miss")
                result_summary = _hit_summary(type_stats) if hit_list else (
                    task_status if task_status != "正常" else "0 命中"
                )
                emit({"type": "task_done", "library_id": library_id, "brand": brand,
                      "keyword": kw, "target_url": target_url, "engine": engine_name,
                      "engine_label": label, "status": result_status,
                      "summary": result_summary, "hit_count": len(hit_list),
                      "first_page": first_page, "first_rank": first_rank,
                      "natural_first_page": type_stats["organic"]["first_page"],
                      "natural_global_rank": type_stats["organic"]["first_global_rank"]})
                emit({"type": "progress", "done": done, "total": total_tasks})
                if hit_list:
                    natural_page = type_stats["organic"]["first_page"]
                    natural_rank = type_stats["organic"]["first_global_rank"]
                    if natural_page:
                        msg = f"[{label}] {kw} → 命中，自然首现第 {natural_page} 页（#{natural_rank}）"
                    else:
                        pos_desc = f"第{first_rank}位" if isinstance(first_rank, int) else str(first_rank or "")
                        msg = f"[{label}] {kw} → 命中，首现第 {first_page} 页（{pos_desc}）"
                else:
                    msg = f"[{label}] {kw} → 未命中"
                emit({"type": "log", "level": "ok" if hit_list else "info", "message": msg})
                time.sleep(random.uniform(0.5, 1.5))
            if stop_flag and stop_flag():
                break
        finally:
            sess.close()
            emit({"type": "log", "level": "info", "message": f"[{label}] 浏览器已关闭"})

    paths = write_reports(outdir, summary_rows, detail_rows, hit_rows, {
        "目标域名": target_label,
        "品牌数": len(brands),
        "开始时间": started_at,
        "结束时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "关键词数": len(tasks),
        "引擎数": len(engines),
        "翻页上限": cfg.max_pages,
        "任务数": stats["tasks"],
        "命中任务数": stats["hit_tasks"],
        "命中记录数": stats["hits"],
        "检查页数": stats["pages"],
    })

    result = {
        "type": "done",
        "outdir": str(outdir),
        "csv": paths.get("csv", ""),
        "xlsx": paths.get("xlsx", ""),
        "summary": {
            "tasks": stats["tasks"], "hit_tasks": stats["hit_tasks"],
            "hits": stats["hits"], "pages": stats["pages"],
            "keywords": len(tasks), "engines": len(engines),
            "brands": len(brands), "targets": targets,
        },
    }
    emit(result)
    return result
