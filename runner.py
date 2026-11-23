from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.checker import run_job
from core.config import JobConfig


def emit(event: dict) -> None:
    """窗口模式下 stdout 可能为 None；此时静默跳过，不影响报告生成。"""
    if sys.stdout is None:
        return
    try:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (AttributeError, BrokenPipeError, OSError):
        pass


def load_config(args) -> JobConfig:
    data: dict = {}
    if args.config:
        path = Path(args.config)
        data = json.loads(path.read_text(encoding="utf-8"))
    if args.keywords:
        data["keywords"] = [x.strip() for x in args.keywords.replace("，", ",").split(",") if x.strip()]
    if args.domain:
        data["target_domain"] = args.domain
    if args.engines:
        names = [x.strip() for x in args.engines.split(",") if x.strip()]
        engines = {n: {"enabled": n in names, "proxy": (data.get("engines", {}).get(n, {}) or {}).get("proxy", "")}
                   for n in ("baidu", "google", "bing", "toutiao")}
        data["engines"] = engines
    if args.pages:
        data["max_pages"] = args.pages
    if args.outdir:
        data["output_dir"] = args.outdir
    if args.visible:
        data["headless"] = False
    return JobConfig.from_dict(data)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="百度/谷歌/必应收录查询引擎")
    parser.add_argument("--config", help="JSON 配置文件路径")
    parser.add_argument("--keywords", help="关键词，逗号分隔")
    parser.add_argument("--domain", help="目标域名")
    parser.add_argument("--engines", help="引擎，逗号分隔：baidu,bing,google,toutiao")
    parser.add_argument("--pages", type=int, help="翻页次数")
    parser.add_argument("--outdir", help="输出目录")
    parser.add_argument("--stopfile", help="停止标记文件路径，出现该文件后优雅退出")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    args = parser.parse_args()

    cfg = load_config(args)
    errs = cfg.validate()
    if errs:
        emit({"type": "fatal", "message": "；".join(errs)})
        return 2

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        emit({"type": "fatal",
              "message": "未安装 Playwright。请在项目目录执行：python -m pip install -r requirements.txt && python -m playwright install chromium"})
        return 3

    stop = threading.Event()

    def _stop(*_):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except Exception:
            pass

    try:
        run_job(
            cfg, emit,
            stop_flag=lambda: stop.is_set() or bool(args.stopfile and Path(args.stopfile).exists()),
            outdir=Path(args.outdir) if args.outdir else None,
        )
    except KeyboardInterrupt:
        emit({"type": "stopped", "message": "已手动停止"})
        return 130
    except Exception as e:
        emit({"type": "fatal", "message": f"{type(e).__name__}: {e}"})
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
