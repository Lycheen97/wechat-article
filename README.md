# WeChat Article

读取微信公众号文章链接或本地 HTML，提取标题、作者、公众号、发布时间和正文，支持 JSON、纯文本、Markdown 及图片导出。可作为 AI 编程助手的 skill，也可独立运行 Python 脚本。

## 环境要求

- Python 3.8+，核心脚本仅使用标准库，无需安装第三方依赖。
- 在线提取需要能访问文章；无需配置 Cookie、账号或 API Key。
- 仓库自带测试建议使用 Python 3.10+（已在 Python 3.11 验证）。

## 安装 skill

下载本仓库（Code → Download ZIP）并解压，将包含 `SKILL.md` 的文件夹命名为 `wechat-article`，放入所用 AI 助手的 skills 目录。

本仓库使用标准 `SKILL.md` 结构；不同客户端的安装目录请以各自配置为准。安装后可向助手发出：

```text
使用 $wechat-article 读取这篇公众号文章并总结：https://mp.weixin.qq.com/s/你的文章ID
```

也可以把本仓库链接发给助手，请它安装这个 skill。

## 独立运行

```bash
git clone https://github.com/Lycheen97/wechat-article.git
cd wechat-article

# 结构化 JSON
python scripts/wechat_article.py "https://mp.weixin.qq.com/s/你的文章ID"

# 纯文本
python scripts/wechat_article.py "https://mp.weixin.qq.com/s/你的文章ID" --text

# Markdown、元数据和图片，按文章分别保存
python scripts/wechat_article.py "https://mp.weixin.qq.com/s/你的文章ID" --markdown -o out

# 本地 HTML：默认离线，不下载图片
python scripts/wechat_article.py --html-file article.html --markdown -o out

# 批量提取：urls.txt 每行一个链接
python scripts/wechat_article.py --batch urls.txt -o out --sleep 5
```

macOS / Linux 若未提供 `python` 命令，请改用 `python3`。

导出文件包括 `article.md`、`metadata.json`，下载图片时还包含 `images/`。如只需远程图片引用，在线导出时加 `--no-images`；本地 HTML 需要下载图片时显式加 `--download-images`。

## 支持范围

支持常见 `js_content` 正文、`cgiDataNew` 文字分享，以及本地 HTML 的 `<article>` 阅读版。遇到微信验证页、受限内容或未知页面模板时，会返回相应错误；不能保证所有文章都可直接抓取。

仅处理有权访问的文章，遵守访问控制与版权要求；批量任务保留间隔，不用于高频抓取。网页验证需要手动处理，不绕过付费、登录或关注限制。

详细用法见 [references/usage.md](references/usage.md)，错误处理见 [references/failures.md](references/failures.md)。

## 验证

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
```

测试使用离线构造数据，不请求真实文章。
