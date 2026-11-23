from __future__ import annotations

import base64
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import host_matches

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_HOST_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}", re.I)


@dataclass
class ResultItem:
    rank: int
    title: str
    href: str
    display: str
    real_url: str = ""
    snippet: str = ""
    links: list[str] = field(default_factory=list)
    kind: str = "organic"          # organic / ad / brand / card
    pos: int = 0                   # 页面结果顺序（含广告、卡片）
    extra_urls: list[str] = field(default_factory=list)
    hit_id: str = ""               # 截图标注用的 DOM 标识


def calc_global_rank(
    page: int,
    pos_in_page: int,
    per_page: int = 10,
    previous_organic: int | None = None,
) -> int:
    """自然结果全局位次。

    默认兼容旧口径：第 N 页第 M 位 = (N-1)*每页条数 + M。
    查询流程传入 previous_organic 时，按前面页实际自然结果数累计，
    以适配头条等一页实际条数可能少于 10 条的引擎。
    """
    if page < 1 or pos_in_page < 1 or per_page < 1:
        raise ValueError("page / pos_in_page / per_page 必须 >= 1")
    if previous_organic is not None:
        if previous_organic < 0:
            raise ValueError("previous_organic 必须 >= 0")
        return previous_organic + pos_in_page
    return (page - 1) * per_page + pos_in_page


KIND_LABEL = {
    "organic": "自然结果",
    "ad": "广告",
    "brand": "品牌专区",
    "card": "聚合卡片",
}


@dataclass
class PageResult:
    page: int
    url: str
    items: list[ResultItem] = field(default_factory=list)
    status: str = "ok"          # ok / no_results / captcha / network_error / error
    message: str = ""


def hostname_of(url: str) -> str:
    if not url:
        return ""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except Exception:
        host = ""
    if host:
        return host.lower()
    m = _HOST_RE.search(url)
    return (m.group(0) if m else "").lower()


def decode_wrapped_url(url: str, engine: str) -> str:
    """把各引擎的跳转链接还原成真实 URL（不发起网络请求）。"""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url
    host = (parsed.hostname or "").lower()
    qs = urllib.parse.parse_qs(parsed.query)
    if engine == "google":
        if (parsed.path in ("/url", "/url/") or host in
                ("google.com", "www.google.com", "google.com.hk", "www.google.com.hk")):
            for key in ("q", "url"):
                if qs.get(key):
                    return qs[key][0]
    if engine == "bing" and "bing.com" in host and parsed.path.startswith("/ck/a"):
        u = (qs.get("u") or [""])[0]
        if u.startswith("a1"):
            u = u[2:]
            try:
                pad = "=" * (-len(u) % 4)
                return base64.urlsafe_b64decode(u + pad).decode("utf-8", "replace")
            except Exception:
                return url
    if engine == "toutiao" and "toutiao.com" in host and "/search/jump" in parsed.path:
        # 头条的跳转链接可能套两层 /search/jump?url=...，逐层拆到真实站点。
        current = url
        for _ in range(3):
            try:
                p = urllib.parse.urlparse(current)
                q = urllib.parse.parse_qs(p.query)
            except Exception:
                break
            if "toutiao.com" not in (p.hostname or "").lower() or "/search/jump" not in p.path:
                break
            inner = (q.get("url") or [""])[0]
            if not inner or inner == current:
                break
            current = inner
        return current
    return url


BAIDU_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return u || ''; } };
  const out = [];
  let seq = 0;
  const nextId = () => { seq += 1; return 'ic-' + seq; };

  // 1) 品牌专区 / 顶部品牌广告：可见位置常把域名换成品牌名，真实 URL 藏在 data-mu
  const topAd = document.querySelector('#top-ad') || document.querySelector('[class*="columbus_banner"]');
  if (topAd) {
    const hitId = nextId();
    topAd.setAttribute('data-ic-hit', hitId);
    const anchors = Array.from(topAd.querySelectorAll('a'));
    const main = topAd.querySelector('a[data-mu]') || anchors[0];
    const mus = [];
    topAd.querySelectorAll('a[data-mu]').forEach((a) => {
      const v = a.getAttribute('data-mu');
      if (v) mus.push(v);
    });
    const titleNode = topAd.querySelector('[class*="banner_title-text"]');
    let title = titleNode ? clean(titleNode.textContent) : '';
    if (!title) title = clean((topAd.innerText || '').split('\n')[0] || '品牌专区');
    out.push({
      kind: 'brand',
      hit_id: hitId,
      title: title,
      href: main ? abs(main.getAttribute('href')) : '',
      mu: mus[0] || '',
      extra_mu: mus,
      display: '品牌专区',
      snippet: clean((topAd.innerText || '').slice(0, 200)),
      links: anchors.map((a) => abs(a.getAttribute('href'))).filter(Boolean).slice(0, 25),
    });
  }

  // 2) 左侧主结果列（自然结果 / 广告 / 富媒体卡片）
  const root = document.querySelector('#content_left');
  if (root) {
    Array.from(root.children).forEach((el) => {
      const h3 = el.querySelector('h3');
      const title = h3 ? clean(h3.textContent) : '';
      if (!title) return;
      const cls = String(el.className || '');
      const tpl = el.getAttribute('tpl') || '';
      if (tpl === 'recommend_list' || cls.includes('recommend')) return;
      let kind = 'organic';
      if (cls.includes('u2a6nht') || cls.includes('ec_') || el.querySelector('[data-placeid]')) kind = 'ad';
      else if (tpl && !tpl.startsWith('www')) kind = 'card';
      const a = h3.closest('a') || el.querySelector('a');
      const href = a ? abs(a.getAttribute('href')) : '';
      let mu = el.getAttribute('mu') || '';
      if (mu === 'null') mu = '';
      const extra_mu = [];
      el.querySelectorAll('a[data-mu], [data-landurl]').forEach((x) => {
        const v = x.getAttribute('data-mu') || x.getAttribute('data-landurl');
        if (v) extra_mu.push(v);
      });
      const showNode = el.querySelector('.c-showurl, .source-text, .siteLink_9TPPp, [class*="showurl"], [class*="source-text"]');
      let display = showNode ? clean(showNode.textContent) : '';
      if (!display) {
        const t = clean((el.innerText || '').slice(0, 120));
        const m = t.match(/(?:[a-z0-9-]+\.)+[a-z]{2,}/i);
        display = m ? m[0] : '';
      }
      if (display.length > 80) display = display.slice(0, 80);
      const hitId = nextId();
      el.setAttribute('data-ic-hit', hitId);
      out.push({
        kind, hit_id: hitId, title, href, mu, extra_mu, display, snippet: '',
        links: Array.from(el.querySelectorAll('a')).map((x) => abs(x.getAttribute('href'))).filter(Boolean).slice(0, 25),
      });
    });
  }
  return out;
}
"""

BING_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  let seq = 0;
  const nextId = () => { seq += 1; return 'ic-' + seq; };
  const items = Array.from(document.querySelectorAll('#b_results > li.b_algo'));
  items.forEach((el) => {
    const a = el.querySelector('h2 a') || el.querySelector('.b_title a') || el.querySelector('a');
    const h3 = el.querySelector('h2');
    if (!a) return;
    const hitId = nextId();
    el.setAttribute('data-ic-hit', hitId);
    const title = clean(h3 ? h3.textContent : a.textContent);
    const citeNode = el.querySelector('cite') || el.querySelector('.b_attribution cite');
    const display = citeNode ? clean(citeNode.textContent) : '';
    const snippetNode = el.querySelector('.b_caption p, .b_snippet, p');
    const snippet = snippetNode ? clean(snippetNode.textContent).slice(0, 300) : '';
    const links = Array.from(el.querySelectorAll('a')).map(x => x.href).filter(Boolean).slice(0, 25);
    out.push({kind: 'organic', hit_id: hitId, title, href: a.href, mu: '', display, snippet, links});
  });
  // 竞价广告
  const ads = Array.from(document.querySelectorAll('#b_results > li.b_ad'));
  ads.forEach((el) => {
    const a = el.querySelector('h2 a') || el.querySelector('a');
    if (!a) return;
    const h2 = el.querySelector('h2');
    const title = clean(h2 ? h2.textContent : a.textContent);
    if (!title) return;
    const hitId = nextId();
    el.setAttribute('data-ic-hit', hitId);
    const citeNode = el.querySelector('cite') || el.querySelector('.b_attribution cite');
    const display = citeNode ? clean(citeNode.textContent) : '广告';
    const links = Array.from(el.querySelectorAll('a')).map(x => x.href).filter(Boolean).slice(0, 25);
    out.push({kind: 'ad', hit_id: hitId, title, href: a.href, mu: '', display, snippet: '', links});
  });
  return out;
}
"""

GOOGLE_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  let seq = 0;
  const nextId = () => { seq += 1; return 'ic-' + seq; };
  const rso = document.querySelector('#rso') || document.querySelector('#search');
  if (!rso) return out;
  const cards = Array.from(rso.querySelectorAll('div')).filter((d) => {
    if (!d.querySelector('h3')) return false;
    const parent = d.parentElement;
    return parent && (parent.id === 'rso' || parent.closest('#rso'));
  });
  const tops = [];
  const h3s = Array.from(rso.querySelectorAll('h3'));
  h3s.forEach((h3) => {
    let card = h3.closest('#rso > div');
    if (!card) card = h3.closest('div.g');
    if (!card) {
      card = h3;
      for (let i = 0; i < 3 && card.parentElement; i++) card = card.parentElement;
    }
    if (tops.includes(card)) return;
    tops.push(card);
    const a = h3.closest('a') || card.querySelector('a');
    if (!a) return;
    const title = clean(h3.textContent);
    if (!title) return;
    const citeNode = card.querySelector('cite');
    const display = citeNode ? clean(citeNode.textContent) : '';
    const snippetNode = card.querySelector('.VwiC3b, .yXK7lf, span[class*="VwiC3b"]');
    const snippet = snippetNode ? clean(snippetNode.textContent).slice(0, 300) : '';
    const links = Array.from(card.querySelectorAll('a')).map(x => x.href).filter(Boolean).slice(0, 25);
    const hitId = nextId();
    card.setAttribute('data-ic-hit', hitId);
    out.push({kind: 'organic', hit_id: hitId, title, href: a.href, mu: '', display, snippet, links});
  });
  // 竞价广告：顶部/底部广告位
  ['#tads', '#tadsb', '#bottomads'].forEach((sel) => {
    const rootAd = document.querySelector(sel);
    if (!rootAd) return;
    Array.from(rootAd.querySelectorAll('h3')).forEach((h3) => {
      const a = h3.closest('a');
      if (!a) return;
      const title = clean(h3.textContent);
      if (!title) return;
      const card = h3.closest('div');
      const citeNode = card ? card.querySelector('cite') : null;
      const display = citeNode ? clean(citeNode.textContent) : '广告';
      const hitId = nextId();
      (card || h3).setAttribute('data-ic-hit', hitId);
      out.push({kind: 'ad', hit_id: hitId, title, href: a.href, mu: '', display, snippet: '', links: [a.href]});
    });
  });
  return out;
}
"""


TOUTIAO_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return u || ''; } };
  const out = [];
  let seq = 0;
  const nextId = () => { seq += 1; return 'ic-' + seq; };

  // 头条页首的“头条热榜”也使用 cs-card-content，但没有 text-xl 标题，直接跳过。
  // “关键词-视频 / 小视频 / 用户 / 图片 / 直播 / 微头条 / 问答 / 话题 / 相关”等是聚合卡片，不能占用自然排名。
  const cards = Array.from(document.querySelectorAll('div.cs-card-content'));
  cards.forEach((el) => {
    const titleLink = el.querySelector('div.text-xl a');
    const headingNode = el.querySelector('div.text-xl');
    const heading = clean(headingNode ? (headingNode.innerText || headingNode.textContent) : '');
    if (!titleLink && !heading) return;

    const links = Array.from(el.querySelectorAll('a'))
      .map((x) => abs(x.getAttribute('href') || x.href))
      .filter(Boolean);
    const isSpecial = /-(视频|小视频|用户|图片|直播|微头条|问答|话题|相关)$/.test(heading) || heading === '相关搜索';

    if (isSpecial && heading && heading !== '相关搜索') {
      const hitId = nextId();
      el.setAttribute('data-ic-hit', hitId);
      out.push({
        kind: 'card', hit_id: hitId, title: heading,
        href: links[0] || '', mu: '', display: '', snippet: '', links: links
      });
      return;
    }
    if (!titleLink) return;

    const title = clean(titleLink.innerText || titleLink.textContent);
    if (!title) return;

    const href = abs(titleLink.getAttribute('href') || titleLink.href);
    const sourceNode = el.querySelector('.cs-source-content .text-ellipsis');
    const snippetNode = el.querySelector('.text-default');
    const display = clean(sourceNode ? (sourceNode.innerText || sourceNode.textContent) : '');
    const snippet = clean(snippetNode ? (snippetNode.innerText || snippetNode.textContent) : '');

    const hitId = nextId();
    el.setAttribute('data-ic-hit', hitId);
    out.push({
      kind: 'organic', hit_id: hitId, title: title, href: href,
      mu: '', display: display, snippet: snippet, links: links
    });
  });
  return out;
}
"""


class BaseEngine:
    name = ""
    label = ""
    wait_selector = ""
    page_size = 10

    def build_url(self, keyword: str, page: int, per_page: int = 10) -> str:
        raise NotImplementedError

    def extract_js(self) -> str:
        raise NotImplementedError

    def blocked_reason(self, url: str, body_text: str) -> str:
        return ""

    def parse_items(self, raw: list[dict[str, Any]]) -> list[ResultItem]:
        items: list[ResultItem] = []
        organic = 0
        seen: set[tuple[str, str]] = set()
        for row in raw:
            href = (row.get("href") or "").strip()
            title = (row.get("title") or "").strip()
            kind = (row.get("kind") or "organic").strip() or "organic"
            key = (kind, title, href)
            if not title or key in seen:
                continue
            seen.add(key)

            extra = [str(x).strip() for x in (row.get("extra_mu") or []) if x and str(x).strip() != "null"]
            mu = str(row.get("mu") or "").strip()
            if mu == "null":
                mu = ""

            if kind == "organic":
                organic += 1

            items.append(
                ResultItem(
                    rank=organic if kind == "organic" else 0,
                    pos=len(items) + 1,
                    title=title,
                    href=href,
                    display=(row.get("display") or "").strip()[:120],
                    snippet=(row.get("snippet") or "").strip(),
                    real_url=mu or (extra[0] if extra else ""),
                    links=[str(x) for x in (row.get("links") or []) if x],
                    kind=kind,
                    extra_urls=extra,
                    hit_id=str(row.get("hit_id") or ""),
                )
            )
        return items


class BaiduEngine(BaseEngine):
    name = "baidu"
    label = "百度"
    wait_selector = "#content_left"

    def build_url(self, keyword: str, page: int, per_page: int = 10) -> str:
        q = urllib.parse.quote(keyword)
        pn = (page - 1) * per_page
        return f"https://www.baidu.com/s?wd={q}&ie=utf-8&rn={per_page}&pn={pn}"

    def extract_js(self) -> str:
        return BAIDU_JS

    def blocked_reason(self, url: str, body_text: str) -> str:
        low = (url or "").lower()
        if "wappass.baidu.com" in low or "/static/captcha" in low:
            return "百度安全验证（验证码），请降低频率或在可见模式下人工验证"
        if "安全验证" in body_text and "百度" in body_text and len(body_text) < 600:
            return "百度安全验证（验证码）"
        return ""


class BingEngine(BaseEngine):
    name = "bing"
    label = "必应"
    wait_selector = "#b_results"

    def build_url(self, keyword: str, page: int, per_page: int = 10) -> str:
        q = urllib.parse.quote(keyword)
        first = (page - 1) * per_page + 1
        return f"https://cn.bing.com/search?q={q}&first={first}&count={per_page}&mkt=zh-CN&setlang=zh-Hans"

    def extract_js(self) -> str:
        return BING_JS

    def blocked_reason(self, url: str, body_text: str) -> str:
        low = (url or "").lower()
        if "captcha" in low or "challenge" in low:
            return "必应人机验证，请降低频率或在可见模式下人工验证"
        if "Verify you are human" in body_text or "请验证你是人类" in body_text:
            return "必应人机验证"
        return ""


class GoogleEngine(BaseEngine):
    name = "google"
    label = "谷歌"
    wait_selector = "#search, #rso"

    def build_url(self, keyword: str, page: int, per_page: int = 10) -> str:
        q = urllib.parse.quote(keyword)
        start = (page - 1) * per_page
        return f"https://www.google.com/search?q={q}&start={start}&num={per_page}&hl=zh-CN"

    def extract_js(self) -> str:
        return GOOGLE_JS

    def blocked_reason(self, url: str, body_text: str) -> str:
        low = (url or "").lower()
        if "consent.google" in low:
            return "谷歌 Cookie 同意页，请检查网络/区域设置"
        if "sorry/index" in low:
            return "谷歌触发异常流量验证（需代理质量较好或人工验证）"
        if "unusual traffic" in body_text.lower() or "detected unusual traffic" in body_text.lower():
            return "谷歌触发异常流量验证"
        return ""


class ToutiaoEngine(BaseEngine):
    name = "toutiao"
    label = "头条搜索"
    wait_selector = "div.text-xl"

    def build_url(self, keyword: str, page: int, per_page: int = 10) -> str:
        q = urllib.parse.quote(keyword)
        if page <= 1:
            return f"https://so.toutiao.com/search?keyword={q}&dvpf=pc"
        # 头条翻页依赖首屏生成的 search_id，不能只靠参数直连；
        # checker 会用“下一页”链接翻页。这里的 URL 仅作日志/兜底展示。
        return (f"https://so.toutiao.com/search?keyword={q}&dvpf=pc"
                f"&pd=synthesis&source=pagination&action_type=pagination"
                f"&page_num={page - 1}")

    def extract_js(self) -> str:
        return TOUTIAO_JS

    def blocked_reason(self, url: str, body_text: str) -> str:
        low = (url or "").lower()
        if "captcha" in low or "wappass" in low or "/verify" in low:
            return "头条搜索触发安全验证，请降低频率或在可见模式下人工验证"
        if "安全验证" in body_text and "头条" in body_text:
            return "头条搜索触发安全验证"
        return ""


ENGINES: dict[str, BaseEngine] = {
    "baidu": BaiduEngine(),
    "bing": BingEngine(),
    "google": GoogleEngine(),
    "toutiao": ToutiaoEngine(),
}


def get_engine(name: str) -> BaseEngine:
    return ENGINES[name]


def judge_hit(item: ResultItem, target: str, engine: str) -> tuple[bool, str]:
    """判定某个结果项是否属于目标域名：真实 URL 优先，可见域名文本兜底。"""
    urls = []
    if item.real_url:
        urls.append(item.real_url)
    urls.extend(item.extra_urls)
    if item.href:
        urls.append(decode_wrapped_url(item.href, engine))
    urls.extend(decode_wrapped_url(u, engine) for u in item.links)

    for u in urls:
        h = hostname_of(u)
        if h and host_matches(h, target):
            return True, u

    # 可见域名位置（百度品牌词会被换成品牌名，此处只做兜底）
    display = (item.display or "").lower()
    if target in display:
        # Google 的 /goto?url= 有时是加密参数，无法还原真实地址；
        # 此时优先用结果卡片的可见域名，避免报告里写成一串跳转链接。
        visible = (item.display or "").strip()
        if visible:
            if "://" in visible:
                return True, visible
            match = _HOST_RE.search(visible)
            if match:
                return True, "https://" + match.group(0)
        return True, item.real_url or item.href
    return False, ""
