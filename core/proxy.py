from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


PROXY_TEST_URLS = {
    "baidu": "https://www.baidu.com/",
    "google": "https://www.google.com/generate_204",
    "bing": "https://cn.bing.com/",
    "toutiao": "https://so.toutiao.com/",
}


def normalize_proxy(raw: str) -> str:
    """校验代理地址，统一成 http://host:port 形式。"""
    value = (raw or "").strip()
    if not value:
        raise ValueError("代理地址为空")
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("只支持 HTTP / HTTPS 代理，例如 http://127.0.0.1:7890")
    if not parts.hostname:
        raise ValueError("代理缺少主机地址")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("代理端口无效") from exc
    if port is None:
        port = 443 if parts.scheme.lower() == "https" else 80
    return f"{parts.scheme.lower()}://{parts.hostname}:{port}"


def test_proxy(raw: str, engine: str = "google", timeout: int = 10) -> tuple[int, float]:
    """通过代理访问对应引擎，返回 (HTTP 状态码, 耗时秒)。"""
    proxy = normalize_proxy(raw)
    if not proxy:
        raise ValueError("代理地址为空")
    url = PROXY_TEST_URLS.get(engine, PROXY_TEST_URLS["google"])
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "IndexChecker/3.0 proxy-check"},
    )
    started = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:
            code = int(response.getcode() or 0)
    except urllib.error.HTTPError as exc:
        code = int(exc.code or 0)
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    elapsed = time.perf_counter() - started
    if code >= 500:
        raise RuntimeError(f"代理返回 HTTP {code}")
    return code, elapsed
