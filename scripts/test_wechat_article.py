#!/usr/bin/env python3
"""Offline regression tests for wechat_article.py."""

from __future__ import annotations

import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

import wechat_article as wa


class WeChatArticleTests(unittest.TestCase):
    def fetch_from(self, raw: str, *, markdown: bool = False) -> dict:
        with mock.patch.object(wa, "fetch_html", return_value=raw):
            return wa.fetch_article(
                "https://mp.weixin.qq.com/s/test",
                want_markdown=markdown,
                retries=0,
            )

    def test_legacy_js_content(self):
        raw = """
        <meta property="og:title" content="Legacy" />
        <div id="js_content"><p>Hello <strong>world</strong></p></div><script></script>
        """
        result = self.fetch_from(raw, markdown=True)
        self.assertEqual(result["content"], "Hello world")
        self.assertEqual(result["content_source"], "js_content")
        self.assertIn("**world**", result["markdown"])

    def test_common_share_plain_text(self):
        raw = r"""
        <body class="page_share_text"><div id="js_article"></div></body>
        <script>
        window.cgiDataNew = {
          user_name: 'gh_test', nick_name: '测试账号', title: '测试标题',
          content_noencode: '第一行\x0a第二行 \x22引号\x22',
          create_time: '2026-08-12 08:08', author: '测试作者',
          is_pay_subscribe: '0' * 1
        };
        </script>
        """
        result = self.fetch_from(raw, markdown=True)
        self.assertNotIn("error", result)
        self.assertEqual(result["content"], '第一行\n第二行 "引号"')
        self.assertEqual(result["content_source"], "cgiDataNew.content_noencode")
        self.assertEqual(result["publish_time"], "2026-08-12 08:08")
        self.assertEqual(result["account"], "测试账号")
        self.assertEqual(result["biz"], "gh_test")
        self.assertEqual(result["images"], [])

    def test_common_share_encoded_html_fallback(self):
        raw = r"""
        <div id="js_article"></div>
        <script>window.cgiDataNew = {
          title: 'Fallback', content: '&lt;p&gt;Hello &amp;amp; goodbye&lt;/p&gt;'
        };</script>
        """
        result = self.fetch_from(raw, markdown=True)
        self.assertEqual(result["content"], "Hello & goodbye")
        self.assertEqual(result["content_source"], "cgiDataNew.content")
        self.assertIn("Hello & goodbye", result["markdown"])

    def test_restricted_content_classification(self):
        raw = "<script>window.cgiDataNew = {is_pay_subscribe: '1' * 1};</script>"
        result = self.fetch_from(raw)
        self.assertEqual(result["error"], "restricted_content")

    def test_unknown_dynamic_template_classification(self):
        raw = '<div id="js_article"></div><script>window.cgiDataNew = {title: \'x\'};</script>'
        result = self.fetch_from(raw)
        self.assertEqual(result["error"], "unsupported_template")

    def test_blocked_verification_still_wins(self):
        result = self.fetch_from("环境异常")
        self.assertEqual(result["error"], "blocked_verification")

    def test_local_html_file_utf8(self):
        raw = """
        <meta property="og:title" content="本地文章" />
        <meta property="og:url" content="https://mp.weixin.qq.com/s/test" />
        <div id="js_content"><p>离线正文</p></div><script></script>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "article.html"
            path.write_text(raw, encoding="utf-8")
            result = wa.parse_html_file(str(path), want_markdown=True)
        self.assertEqual(result["title"], "本地文章")
        self.assertEqual(result["content"], "离线正文")
        self.assertEqual(result["content_source"], "js_content")
        self.assertEqual(result["input_source"], "local_html")
        self.assertEqual(result["source_encoding"], "utf-8")
        self.assertEqual(result["url"], "https://mp.weixin.qq.com/s/test")

    def test_local_html_file_gb18030_despite_utf8_declaration(self):
        raw = """
        <meta charset="utf-8"><title>中文标题</title>
        <div id="js_content"><p>中文正文</p></div><script></script>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "article.html"
            path.write_bytes(raw.encode("gb18030"))
            result = wa.parse_html_file(str(path))
        self.assertEqual(result["title"], "中文标题")
        self.assertEqual(result["content"], "中文正文")
        self.assertEqual(result["source_encoding"], "gb18030")

    def test_local_standalone_article_element(self):
        raw = "<title>离线阅读版</title><article><p>可直接解析</p></article>"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "readable.html"
            path.write_text(raw, encoding="utf-8")
            result = wa.parse_html_file(str(path), want_markdown=True)
        self.assertEqual(result["content"], "可直接解析")
        self.assertEqual(result["content_source"], "article_element")
        self.assertIn("可直接解析", result["markdown"])

    def test_local_output_directory_is_offline_by_default(self):
        raw = """
        <title>Offline</title>
        <div id="js_content"><p>Body</p><img data-src="https://example.com/a.png"></div><script></script>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "article.html"
            output = Path(temp_dir) / "out"
            source.write_text(raw, encoding="utf-8")
            args = SimpleNamespace(
                html_file=str(source), markdown=False, output_dir=str(output),
                download_images=False, no_images=False, text=False,
            )
            with (
                mock.patch.object(wa, "download_images") as download,
                mock.patch.object(wa, "fetch_html", side_effect=AssertionError("network fetch")),
                mock.patch.object(wa, "_http_get", side_effect=AssertionError("network fetch")),
            ):
                rc = wa.cmd_html_file(args)
            self.assertEqual(rc, 0)
            download.assert_not_called()
            self.assertTrue(any(output.rglob("article.md")))

    def test_local_image_download_requires_explicit_flag(self):
        raw = """
        <title>Offline</title>
        <div id="js_content"><img data-src="https://example.com/a.png"></div><script></script>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "article.html"
            output = Path(temp_dir) / "out"
            source.write_text(raw, encoding="utf-8")
            args = SimpleNamespace(
                html_file=str(source), markdown=False, output_dir=str(output),
                download_images=True, no_images=False, text=False,
            )
            with mock.patch.object(wa, "download_images", return_value={}) as download:
                rc = wa.cmd_html_file(args)
            self.assertEqual(rc, 0)
            download.assert_called_once()

    def test_input_modes_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with mock.patch.object(wa.sys, "stderr", stderr):
            rc = wa.main([
                "https://mp.weixin.qq.com/s/test",
                "--html-file",
                "article.html",
            ])
        self.assertEqual(rc, 2)
        self.assertIn("必须且只能提供一种", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
