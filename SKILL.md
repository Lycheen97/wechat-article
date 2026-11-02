---
name: wechat-article
description: 读取微信公众号文章链接或本地微信文章 HTML，提取正文与图片。
---

# WeChat Article

Use `scripts/wechat_article.py` relative to this skill with Python 3.8+.
It uses the standard library and requires no login, cookie or third-party package.
For a supplied URL, `python "<skill-dir>/scripts/wechat_article.py" "<URL>"`
returns structured JSON; use it for reading or summarization.

- Local HTML, Markdown/images or batch output: read [usage](references/usage.md)
  for the selected mode. Local HTML stays offline unless image downloads are requested.
- Errors, verification pages or missing content: read [failure handling](references/failures.md).
  The parser supports `js_content`, `cgiDataNew` text shares and offline `<article>` exports.

Process supplied or otherwise authorized URLs, respect access controls and copyright,
and preserve batch throttling. Store temporary artifacts under the system temp directory.
Check that the extracted title and body match the requested article; repair supported
parser failures or use the documented browser fallback before reporting a coverage gap.
Keep JSON error fields and stdout/stderr separation stable when maintaining the parser.
