# Article extraction modes

Read the section matching local HTML, Markdown/images, or batch output.


Run from the skill directory with Python available on PATH (Windows PowerShell example):

```powershell
$py = 'python'
$script = './scripts/wechat_article.py'

# Text-only structured JSON; does not include images by default
& $py $script 'https://mp.weixin.qq.com/s/XXXXX'

# Parse a browser-saved or clean offline HTML file without network access
& $py $script --html-file 'C:\path\article.html'

# Plain text to stdout
& $py $script 'https://mp.weixin.qq.com/s/XXXXX' --text

# Plain text from local HTML
& $py $script --html-file 'C:\path\article.html' --text

# Default for article reading: Markdown plus images; open the images before summarizing
& $py $script 'https://mp.weixin.qq.com/s/XXXXX' --markdown -o "$env:TEMP\wechat-article"

# Local HTML to Markdown; keeps image references and remains offline by default
& $py $script --html-file 'C:\path\article.html' -o "$env:TEMP\wechat-article"

# Explicitly allow image downloads while converting local HTML
& $py $script --html-file 'C:\path\article.html' -o "$env:TEMP\wechat-article" --download-images

# Batch known URLs from a text file
& $py $script --batch 'C:\path\urls.txt' -o 'C:\path\articles' --sleep 5
```

`URL`, `--html-file`, and `--batch` are mutually exclusive input modes. For URL
reading, analysis and summarization, use `--markdown -o` by default, then read
`article.md` and open every downloaded image. The script extracts and downloads
images; visual interpretation is performed by the host assistant, not the script.
Use a unique output directory under the system temp directory for each task to
avoid mixing old images with new articles. Plain JSON and `--text` are for an
explicit text-only request or a confirmed image-free article.

Local HTML mode must remain offline by default: it reads and parses the supplied
file but does not fetch the article or download its images. Inspect available local images as part of reading. Use `--download-images` only
when remote image access is authorized, and honor explicit offline constraints.
If remote images are unavailable, identify the missing visual content in the answer. The result adds `input_source: local_html`, `source_file`, and
`source_encoding` while retaining `content_source` to identify the parser path.
