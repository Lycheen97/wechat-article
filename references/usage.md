# Article extraction modes

Read the section matching local HTML, Markdown/images, or batch output.


Run from the skill directory with Python available on PATH (Windows PowerShell example):

```powershell
$py = 'python'
$script = './scripts/wechat_article.py'

# Structured JSON to stdout; default for agent consumption
& $py $script 'https://mp.weixin.qq.com/s/XXXXX'

# Parse a browser-saved or clean offline HTML file without network access
& $py $script --html-file 'C:\path\article.html'

# Plain text to stdout
& $py $script 'https://mp.weixin.qq.com/s/XXXXX' --text

# Plain text from local HTML
& $py $script --html-file 'C:\path\article.html' --text

# Markdown plus downloaded article images
& $py $script 'https://mp.weixin.qq.com/s/XXXXX' --markdown -o "$env:TEMP\wechat-article"

# Local HTML to Markdown; keeps image references and remains offline by default
& $py $script --html-file 'C:\path\article.html' -o "$env:TEMP\wechat-article"

# Explicitly allow image downloads while converting local HTML
& $py $script --html-file 'C:\path\article.html' -o "$env:TEMP\wechat-article" --download-images

# Batch known URLs from a text file
& $py $script --batch 'C:\path\urls.txt' -o 'C:\path\articles' --sleep 5
```

`URL`, `--html-file`, and `--batch` are mutually exclusive input modes. Prefer
JSON for analysis and summarization. Use Markdown mode only when the user asks
for a local artifact or image preservation. Put temporary output under `%TEMP%`,
not the desktop.

Local HTML mode must remain offline by default: it reads and parses the supplied
file but does not fetch the article or download its images. Only use
`--download-images` when the user wants local image copies and network access is
available. The result adds `input_source: local_html`, `source_file`, and
`source_encoding` while retaining `content_source` to identify the parser path.
