---
name: wechat-article
description: 读取微信公众号文章链接或本地微信文章 HTML，默认结合正文、图片文字与图表理解文章。
---

# WeChat Article

Use `scripts/wechat_article.py` relative to this skill with Python 3.8+.
It uses the standard library and requires no login, cookie or third-party package.

## Default: read both text and images

For article reading, analysis or summarization, export the supplied URL with:

```text
python "<skill-dir>/scripts/wechat_article.py" "<URL>" --markdown -o "<unique-system-temp-directory>"
```

This saves `article.md`, `metadata.json` and downloaded `images/` in an article
subdirectory. Read the text and open the downloaded images with the host's image
viewing capability before answering. A download, an image URL or alt text alone
does not count as reading an image. Inspect every article image; after inspection,
decorative logos, QR codes and ads need not be included in the summary.

Read text screenshots, tables and charts alongside the surrounding paragraphs,
preserving their order and context. For charts, inspect labels, units, dates and
legends. For long or dense images, zoom or inspect readable sections rather than
relying on an unreadable thumbnail. Use OCR if available when useful, and check
important figures against the image. Combine visual evidence with the article
text; do not infer image contents solely from captions.

If downloads fail, inspect the remaining remote images through an available
browser/image tool. If an image cannot be viewed or read, briefly identify that
specific gap in the answer instead of treating it as reviewed. If the host lacks
image viewing, say that only the text was read. Do not silently fall back to
text-only reading. Use text-only mode only when the user explicitly requests it
or the article has no images.

- Local HTML, output options or batch output: read [usage](references/usage.md).
  Local HTML stays offline by default; inspect available local images and report
  unavailable remote images. Download remote images only when network access is
  authorized; honor any explicit offline constraint.
- Errors, verification pages or missing content: read [failure handling](references/failures.md).
  The parser supports `js_content`, `cgiDataNew` text shares and offline `<article>` exports.

Process supplied or otherwise authorized URLs, respect access controls and copyright,
and preserve batch throttling. Store temporary artifacts under the system temp directory.
Check that the extracted title, body and images match the requested article; repair
supported parser failures or use the documented browser fallback before reporting a gap.
Keep JSON error fields and stdout/stderr separation stable when maintaining the parser.
