#!/usr/bin/env python3
"""微信公众号文章抓取与导出工具

用法概览：
  python wechat_article.py URL                                # 取单篇，stdout JSON
  python wechat_article.py URL --text                         # stdout 纯文本
  python wechat_article.py URL --markdown -o out/             # 输出 Markdown + 图片
  python wechat_article.py --batch urls.txt -o out/           # 批量处理
  python wechat_article.py URL --markdown --no-images -o out/ # Markdown 不下载图片

仅依赖 Python 3.8+ 标准库。
"""

from __future__ import annotations

import argparse
import codecs
import datetime
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


VERSION = "1.2.0"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

IMAGE_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Referer": "https://mp.weixin.qq.com/",
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_get(url: str, headers: dict, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_html(url: str, timeout: int = 20) -> str:
    raw = _http_get(url, REQUEST_HEADERS, timeout=timeout)
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_JS_SIMPLE_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "/": "/",
}


def _decode_js_string(value: str) -> str:
    """Decode the body of a JavaScript string literal without executing JS."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        i += 1
        if i >= len(value):
            out.append("\\")
            break

        esc = value[i]
        if esc == "\r" or esc == "\n":
            if esc == "\r" and i + 1 < len(value) and value[i + 1] == "\n":
                i += 1
            i += 1
            continue
        if esc in _JS_SIMPLE_ESCAPES:
            out.append(_JS_SIMPLE_ESCAPES[esc])
            i += 1
            continue
        if esc == "x" and i + 2 < len(value):
            digits = value[i + 1 : i + 3]
            if re.fullmatch(r"[0-9a-fA-F]{2}", digits):
                out.append(chr(int(digits, 16)))
                i += 3
                continue
        if esc == "u":
            if i + 1 < len(value) and value[i + 1] == "{":
                end = value.find("}", i + 2)
                digits = value[i + 2 : end] if end >= 0 else ""
                if digits and re.fullmatch(r"[0-9a-fA-F]{1,6}", digits):
                    codepoint = int(digits, 16)
                    if codepoint <= 0x10FFFF:
                        out.append(chr(codepoint))
                        i = end + 1
                        continue
            elif i + 4 < len(value):
                digits = value[i + 1 : i + 5]
                if re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    codepoint = int(digits, 16)
                    i += 5
                    if 0xD800 <= codepoint <= 0xDBFF and value[i : i + 2] == "\\u":
                        low_digits = value[i + 2 : i + 6]
                        if re.fullmatch(r"[0-9a-fA-F]{4}", low_digits):
                            low = int(low_digits, 16)
                            if 0xDC00 <= low <= 0xDFFF:
                                codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
                                i += 6
                    out.append(chr(codepoint) if not 0xD800 <= codepoint <= 0xDFFF else "\ufffd")
                    continue

        # JavaScript treats an otherwise unknown escape as the escaped character.
        out.append(esc)
        i += 1
    return "".join(out)


def _extract_js_string_field(raw: str, field: str, *, start: int = 0) -> str | None:
    """Extract one quoted object field from JavaScript source safely."""
    pattern = re.compile(rf"(?<![\w$]){re.escape(field)}\s*:\s*(['\"])")
    match = pattern.search(raw, max(0, start))
    if not match:
        return None

    quote = match.group(1)
    value_start = match.end()
    i = value_start
    while i < len(raw):
        ch = raw[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return _decode_js_string(raw[value_start:i])
        i += 1
    return None


def extract_cgi_data_new(raw: str) -> dict:
    """Extract fields embedded in WeChat's common_share cgiDataNew payload."""
    start = raw.find("window.cgiDataNew")
    if start < 0:
        return {}
    fields = (
        "title",
        "nick_name",
        "author",
        "user_name",
        "create_time",
        "content_noencode",
        "content",
        "is_pay_subscribe",
    )
    return {
        field: value
        for field in fields
        if (value := _extract_js_string_field(raw, field, start=start)) is not None
    }

def _extract_first(patterns, raw):
    for p in patterns:
        m = re.search(p, raw, re.DOTALL)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def extract_metadata(raw: str, cgi_data: dict | None = None) -> dict:
    # WeChat declares vars like:
    #   var msg_title = htmlDecode("...").html(false);
    #   var nickname = htmlDecode("...");
    # Inner Chinese smart quotes (U+201C/D) are NOT ASCII quotes, so we can
    # safely capture between ASCII "/' delimiters using a non-quote class.
    cgi_data = cgi_data or {}
    meta = {
        "title": _extract_first(
            [
                r'var msg_title\s*=\s*(?:htmlDecode\()?["\']([^"\']+)["\']',
                r'<meta property="og:title" content="([^"]+)"',
                r'<title>([^<]+)</title>',
            ],
            raw,
        ) or cgi_data.get("title"),
        "account": _extract_first(
            [
                r'var nickname\s*=\s*(?:htmlDecode\()?["\']([^"\']+)["\']',
                r'<meta property="og:article:author" content="([^"]+)"',
            ],
            raw,
        ) or cgi_data.get("nick_name"),
        "author": _extract_first(
            [r'id="js_author_name"[^>]*>([^<]+)<'],
            raw,
        ) or cgi_data.get("author"),
        "biz": _extract_first([r'var biz\s*=\s*["\']([^"\']+)["\']'], raw)
        or cgi_data.get("user_name"),
    }
    m = re.search(r'var ct\s*=\s*["\'](\d+)["\']', raw)
    if m:
        meta["publish_time"] = datetime.datetime.fromtimestamp(int(m.group(1))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    else:
        meta["publish_time"] = cgi_data.get("create_time")
    return meta


def extract_body_html(raw: str) -> str | None:
    """Return the inner HTML of #js_content, or None if not found."""
    m = re.search(
        r'id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div class="ct_mpda_wrp")',
        raw,
        re.DOTALL,
    )
    if not m:
        m = re.search(r'id="js_content"[^>]*>(.*?)</div>', raw, re.DOTALL)
    return m.group(1) if m else None


def extract_article_element_html(raw: str) -> str | None:
    """Return the inner HTML of a standalone <article> element, if present."""
    m = re.search(r"<article\b[^>]*>(.*?)</article\s*>", raw, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def extract_source_url(raw: str) -> str | None:
    """Best-effort recovery of the original article URL from saved HTML."""
    return _extract_first(
        [
            r'<meta\s+property=["\']og:url["\']\s+content=["\']([^"\']+)["\']',
            r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
            r'var\s+msg_link\s*=\s*["\']([^"\']+)["\']',
        ],
        raw,
    )


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

INLINE_TAGS = {"strong", "b", "em", "i", "a", "code", "span", "u", "sup", "sub"}
BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "li",
    "ul",
    "ol",
    "pre",
    "table",
    "tr",
    "td",
    "th",
}


class _MarkdownBuilder(HTMLParser):
    """Walk the article body HTML and emit Markdown.

    Behaviour:
        - Preserves headings, bold/italic, links, blockquotes, lists, images.
        - <img>'s real URL lives in data-src (lazy-load); falls back to src.
        - Collected images list is exposed via .images for post-processing.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.images: list[dict] = []  # [{url, alt, idx}]
        self._stack: list[str] = []
        self._link_href: list[str] = []
        self._list_stack: list[tuple] = []  # (type, counter)
        self._in_pre = 0
        self._in_blockquote = 0
        self._img_idx = 0

    def _emit(self, s: str) -> None:
        self.out.append(s)

    def _ensure_block_break(self) -> None:
        if not self.out:
            return
        tail = "".join(self.out[-2:])
        if not tail.endswith("\n\n"):
            if tail.endswith("\n"):
                self._emit("\n")
            else:
                self._emit("\n\n")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in {"p", "div", "section"}:
            self._ensure_block_break()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._ensure_block_break()
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._ensure_block_break()
            self._emit("---\n\n")
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._ensure_block_break()
            self._emit("```\n")
            self._in_pre += 1
        elif tag == "blockquote":
            self._ensure_block_break()
            self._in_blockquote += 1
        elif tag == "a":
            self._link_href.append(a.get("href", ""))
            self._emit("[")
        elif tag == "img":
            url = a.get("data-src") or a.get("src") or ""
            alt = a.get("alt", "")
            if url and not url.startswith("data:"):
                self._img_idx += 1
                self.images.append({"url": url, "alt": alt, "idx": self._img_idx})
                self._ensure_block_break()
                self._emit(f"![{alt}]({url})")
                self._emit("\n\n")
        elif tag == "ul":
            self._list_stack.append(("ul", 0))
            self._ensure_block_break()
        elif tag == "ol":
            self._list_stack.append(("ol", 0))
            self._ensure_block_break()
        elif tag == "li":
            if self._list_stack:
                typ, n = self._list_stack[-1]
                n += 1
                self._list_stack[-1] = (typ, n)
                indent = "  " * (len(self._list_stack) - 1)
                bullet = "- " if typ == "ul" else f"{n}. "
                self._emit(f"\n{indent}{bullet}")
            else:
                self._emit("\n- ")
        elif tag == "table":
            self._ensure_block_break()
        elif tag == "tr":
            self._emit("\n| ")
        elif tag in {"td", "th"}:
            self._emit(" | ")
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag in {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._emit("\n\n")
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._emit("\n```\n\n")
            self._in_pre = max(0, self._in_pre - 1)
        elif tag == "blockquote":
            self._in_blockquote = max(0, self._in_blockquote - 1)
            self._emit("\n\n")
        elif tag == "a":
            href = self._link_href.pop() if self._link_href else ""
            if href:
                self._emit(f"]({href})")
            else:
                self._emit("]")
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
            self._emit("\n\n")
        elif tag == "li":
            pass
        elif tag == "tr":
            self._emit(" |")

    def handle_data(self, data):
        if not data:
            return
        if self._in_pre:
            self._emit(data)
            return
        # In blockquote, prepend "> " on new lines (best-effort).
        if self._in_blockquote and self.out and self.out[-1].endswith("\n"):
            data = re.sub(r"\n(?!$)", "\n> ", data)
            if not data.startswith(">"):
                data = "> " + data
        self._emit(data)

    def result(self) -> str:
        text = "".join(self.out)
        # Collapse 3+ blank lines.
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Trim trailing whitespace per line.
        lines = [ln.rstrip() for ln in text.split("\n")]
        text = "\n".join(lines).strip() + "\n"
        return text


def body_to_markdown(body_html: str) -> tuple[str, list[dict]]:
    builder = _MarkdownBuilder()
    builder.feed(body_html)
    builder.close()
    return builder.result(), builder.images


def body_to_text(body_html: str) -> str:
    body = re.sub(r"<br\s*/?>", "\n", body_html)
    body = re.sub(r"</p>", "\n\n", body)
    body = re.sub(r"</div>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body)
    lines = [ln.strip() for ln in body.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text


_HTML_CONTENT_RE = re.compile(
    r"<(?:p|div|section|br|img|h[1-6]|blockquote|ul|ol|li|table|pre|strong|em)\b",
    re.IGNORECASE,
)


def cgi_data_to_content(cgi_data: dict, *, want_markdown: bool = False) -> dict | None:
    """Convert a common_share cgiDataNew payload into normal result fields."""
    plain = (cgi_data.get("content_noencode") or "").strip()
    encoded = cgi_data.get("content") or ""
    decoded = html.unescape(encoded).strip()
    has_html = bool(_HTML_CONTENT_RE.search(decoded))

    if plain:
        content = plain
        source = "cgiDataNew.content_noencode"
    elif decoded:
        content = body_to_text(decoded) if has_html else decoded
        source = "cgiDataNew.content"
    else:
        return None

    result = {"content": content, "content_source": source}
    if want_markdown:
        if has_html:
            markdown, images = body_to_markdown(decoded)
        else:
            markdown = content.rstrip() + "\n"
            images = []
        result["markdown"] = markdown
        result["images"] = images
    return result


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------

EXT_RE = re.compile(r"wx_fmt=([a-z0-9]+)", re.IGNORECASE)


def _guess_ext(url: str) -> str:
    m = EXT_RE.search(url)
    if m:
        ext = m.group(1).lower()
        if ext in {"jpeg", "jpg", "png", "gif", "webp", "bmp"}:
            return "jpg" if ext == "jpeg" else ext
    # Fallback: look at path
    path = urllib.parse.urlparse(url).path
    for ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
        if path.lower().endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    return "jpg"


def download_images(images: list[dict], target_dir: str, sleep: float = 0.3) -> dict[str, str]:
    """Download images into target_dir/images/. Returns {original_url: relative_path}."""
    if not images:
        return {}
    img_dir = os.path.join(target_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    mapping: dict[str, str] = {}
    for img in images:
        url = img["url"]
        idx = img["idx"]
        ext = _guess_ext(url)
        filename = f"img_{idx:03d}.{ext}"
        filepath = os.path.join(img_dir, filename)
        rel = f"images/{filename}"
        try:
            data = _http_get(url, IMAGE_HEADERS, timeout=20)
            with open(filepath, "wb") as f:
                f.write(data)
            mapping[url] = rel
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"  [warn] image {idx} download failed: {e}", file=sys.stderr)
            mapping[url] = url  # leave original URL in markdown
        time.sleep(sleep)
    return mapping


def rewrite_image_refs(markdown: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return markdown
    for orig, new in mapping.items():
        markdown = markdown.replace(f"]({orig})", f"]({new})")
    return markdown


# ---------------------------------------------------------------------------
# Top-level fetch
# ---------------------------------------------------------------------------

class FetchError(Exception):
    pass


def parse_article_html(
    raw: str,
    *,
    want_markdown: bool = False,
    allow_article_element: bool = False,
) -> dict:
    """Parse one WeChat article HTML document without performing network I/O."""
    result = {"raw_length": len(raw)}

    if "环境异常" in raw:
        result["error"] = "blocked_verification"
        result["error_hint"] = "微信安全验证拦截，请稍后再试或换 IP"
        return result

    cgi_data = extract_cgi_data_new(raw)
    result.update(extract_metadata(raw, cgi_data))

    body = extract_body_html(raw)
    content_source = "js_content"
    if body is None and allow_article_element:
        body = extract_article_element_html(raw)
        content_source = "article_element"
    if body is not None:
        result["content"] = body_to_text(body)
        result["content_source"] = content_source
        if want_markdown:
            md, imgs = body_to_markdown(body)
            result["markdown"] = md
            result["images"] = imgs
        return result

    cgi_content = cgi_data_to_content(cgi_data, want_markdown=want_markdown)
    if cgi_content:
        result.update(cgi_content)
        return result

    if cgi_data.get("is_pay_subscribe") == "1" or any(
        marker in raw for marker in ("付费后可阅读全文", "关注后可查看全文")
    ):
        result["error"] = "restricted_content"
        result["error_hint"] = "正文需要付费、登录或关注后查看"
    elif "window.cgiDataNew" in raw or re.search(r'id=["\']js_article["\']', raw):
        result["error"] = "unsupported_template"
        result["error_hint"] = "收到微信文章页面，但内嵌正文结构尚未被解析器支持"
    else:
        result["error"] = "no_content_found"
        result["error_hint"] = "页面中未找到可识别的文章正文"
    return result


def decode_html_bytes(data: bytes) -> tuple[str, str]:
    """Decode browser-saved HTML, tolerating common Chinese legacy encodings."""
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16"), "utf-16"

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    head = data[:8192].decode("ascii", errors="ignore")
    match = re.search(r"""charset\s*=\s*["']?\s*([a-zA-Z0-9._-]+)""", head, re.IGNORECASE)
    declared = match.group(1).lower() if match else ""
    if declared in {"gb2312", "gbk", "gb18030"}:
        candidates = ("gb18030",)
    elif declared:
        candidates = (declared, "gb18030")
    else:
        candidates = ("gb18030",)

    for encoding in candidates:
        try:
            return data.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def parse_html_file(path: str, *, want_markdown: bool = False) -> dict:
    """Read and parse local HTML without fetching the article or its images."""
    with open(path, "rb") as f:
        raw, encoding = decode_html_bytes(f.read())
    result = parse_article_html(
        raw,
        want_markdown=want_markdown,
        allow_article_element=True,
    )
    result["input_source"] = "local_html"
    result["source_file"] = path
    result["source_encoding"] = encoding
    result["parsed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if source_url := extract_source_url(raw):
        result["url"] = source_url
    return result


def fetch_article(
    url: str,
    *,
    want_markdown: bool = False,
    timeout: int = 20,
    retries: int = 2,
    retry_sleep: float = 3.0,
) -> dict:
    """Fetch an article. Returns dict with metadata + content (and markdown if requested)."""
    raw = None
    last_err = None
    for attempt in range(retries + 1):
        try:
            raw = fetch_html(url, timeout=timeout)
            break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(retry_sleep)
    if raw is None:
        raise FetchError(f"network error: {last_err}")

    result = parse_article_html(raw, want_markdown=want_markdown)
    result["url"] = url
    result["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    return result


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

INVALID_FN_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_filename(name: str, fallback: str = "article", maxlen: int = 80) -> str:
    if not name:
        return fallback
    cleaned = INVALID_FN_CHARS.sub("_", name).strip(" .")
    cleaned = cleaned[:maxlen] or fallback
    return cleaned


def _slug_dir(meta: dict, idx: int) -> str:
    title = meta.get("title") or f"article_{idx}"
    pt = meta.get("publish_time") or ""
    date_prefix = pt[:10].replace("-", "") if pt else ""
    parts = [p for p in (date_prefix, safe_filename(title)) if p]
    return "_".join(parts) if parts else safe_filename(title, fallback=f"article_{idx}")


def write_article_dir(out_root: str, meta: dict, idx: int, *, download_imgs: bool) -> str:
    """Write metadata.json + article.md (and optionally images/) under out_root/<slug>/."""
    slug = _slug_dir(meta, idx)
    target = os.path.join(out_root, slug)
    os.makedirs(target, exist_ok=True)

    md_text = meta.get("markdown") or meta.get("content") or ""

    if download_imgs and meta.get("images"):
        mapping = download_images(meta["images"], target)
        if md_text:
            md_text = rewrite_image_refs(md_text, mapping)

    header_lines = []
    if meta.get("title"):
        header_lines.append(f"# {meta['title']}\n")
    src_bits = []
    if meta.get("account"):
        src_bits.append(meta["account"])
    if meta.get("author") and meta.get("author") != meta.get("account"):
        src_bits.append(meta["author"])
    if meta.get("publish_time"):
        src_bits.append(meta["publish_time"])
    if src_bits:
        header_lines.append("> " + " · ".join(src_bits))
        header_lines.append(f"> 原文：{meta.get('url', '')}\n")
    header = "\n".join(header_lines) + ("\n" if header_lines else "")

    md_path = os.path.join(target, "article.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(header + (md_text or ""))

    meta_for_json = {k: v for k, v in meta.items() if k not in {"markdown", "content"}}
    with open(os.path.join(target, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta_for_json, f, ensure_ascii=False, indent=2)

    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_url_list(path: str) -> list[str]:
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def cmd_single(args) -> int:
    want_md = args.markdown or bool(args.output_dir)
    try:
        result = fetch_article(args.url, want_markdown=want_md, timeout=args.timeout)
    except FetchError as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 2

    return emit_single_result(args, result, download_imgs=not args.no_images)


def emit_single_result(args, result: dict, *, download_imgs: bool) -> int:
    if result.get("error"):
        print(f"warning: {result['error']} ({result.get('error_hint', '')})", file=sys.stderr)
        if not args.output_dir:
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            print()
            return 1

    if args.output_dir:
        target = write_article_dir(
            args.output_dir, result, idx=1, download_imgs=download_imgs
        )
        print(f"saved: {target}")
        return 0

    if args.text:
        if result.get("title"):
            print(f"# {result['title']}")
        if result.get("account"):
            print(f"来源: {result['account']}")
        if result.get("publish_time"):
            print(f"时间: {result['publish_time']}")
        print()
        print(result.get("content") or "")
    elif args.markdown:
        sys.stdout.write(result.get("markdown") or "")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0


def cmd_html_file(args) -> int:
    want_md = args.markdown or bool(args.output_dir)
    try:
        result = parse_html_file(args.html_file, want_markdown=want_md)
    except (OSError, UnicodeError) as e:
        print(f"read failed: {e}", file=sys.stderr)
        return 2
    return emit_single_result(
        args,
        result,
        download_imgs=args.download_images and not args.no_images,
    )


def cmd_batch(args) -> int:
    urls = _read_url_list(args.batch)
    if not urls:
        print("no URLs in batch file", file=sys.stderr)
        return 2
    out_root = args.output_dir or "wechat_articles"
    os.makedirs(out_root, exist_ok=True)
    print(f"batch: {len(urls)} URL(s) → {out_root}/")

    summary = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        try:
            result = fetch_article(url, want_markdown=True, timeout=args.timeout)
        except FetchError as e:
            print(f"  fetch failed: {e}", file=sys.stderr)
            summary.append({"url": url, "ok": False, "error": str(e)})
            time.sleep(args.sleep + random.uniform(0, 1))
            continue

        if result.get("error"):
            print(f"  {result['error']}: {result.get('error_hint', '')}", file=sys.stderr)
            summary.append({"url": url, "ok": False, "error": result["error"]})
        else:
            target = write_article_dir(out_root, result, idx=i, download_imgs=not args.no_images)
            print(f"  → {target}")
            summary.append(
                {"url": url, "ok": True, "title": result.get("title"), "path": target}
            )
        time.sleep(args.sleep + random.uniform(0, 1))

    with open(os.path.join(out_root, "_batch_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    ok = sum(1 for s in summary if s["ok"])
    print(f"done: {ok}/{len(urls)} succeeded")
    return 0 if ok == len(urls) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wechat_article",
        description="微信公众号文章抓取与导出工具 (v" + VERSION + ")",
    )
    p.add_argument("url", nargs="?", help="单篇文章 URL (mp.weixin.qq.com/s/...)")
    p.add_argument("--batch", metavar="FILE", help="批量模式：从文件读取 URL 列表（每行一条，# 开头为注释）")
    p.add_argument("--html-file", metavar="FILE", help="离线模式：解析本地保存的微信文章 HTML")
    p.add_argument("-o", "--output-dir", metavar="DIR", help="输出目录：每篇文章一个子目录")
    p.add_argument("--markdown", action="store_true", help="输出 Markdown（含图片引用）")
    p.add_argument("--text", action="store_true", help="输出纯文本（去 HTML）")
    image_group = p.add_mutually_exclusive_group()
    image_group.add_argument("--no-images", action="store_true", help="不下载图片（保留远程 URL）")
    image_group.add_argument(
        "--download-images",
        action="store_true",
        help="本地 HTML 模式显式下载正文图片（默认完全离线）",
    )
    p.add_argument("--timeout", type=int, default=20, help="单次 HTTP 超时秒数 (default 20)")
    p.add_argument("--sleep", type=float, default=2.0, help="批量模式下文章间隔秒数 (default 2.0)")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return p


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv=None) -> int:
    _ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    input_count = sum(bool(value) for value in (args.url, args.batch, args.html_file))
    if input_count != 1:
        print("error: URL、--batch 和 --html-file 必须且只能提供一种", file=sys.stderr)
        return 2
    if args.batch:
        return cmd_batch(args)
    if args.html_file:
        return cmd_html_file(args)
    return cmd_single(args)


if __name__ == "__main__":
    sys.exit(main())
