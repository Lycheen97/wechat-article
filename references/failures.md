# Article extraction failures

Read only when extraction reports an error or incomplete content.


- Treat `blocked_verification` as WeChat anti-bot throttling. Wait, reduce frequency, or ask the user to open the article manually; do not attempt to bypass verification.
- Treat `restricted_content` as a paid, login-only, or follower-only boundary.
- Treat `unsupported_template` as parser drift. If the current client has a browser capability, render the user-supplied URL and inspect the article DOM as a fallback; otherwise report the unsupported template.
- Treat `no_content_found` as a page with no recognizable article payload. Report the boundary instead of inventing missing content.
- Treat `read failed` as a missing, unreadable, or invalid local file boundary.
- Use the additive `content_source` result field (`js_content`, `article_element`, `cgiDataNew.content_noencode`, or `cgiDataNew.content`) when diagnosing extraction behavior.
- Preserve batch sleep and jitter. Do not use the tool for high-frequency account-wide scraping.
- Respect article copyright. Fetch only user-supplied or otherwise authorized URLs, and do not republish content without permission.

The script is intentionally Python-standard-library only. Keep its JSON error fields and stdout/stderr separation stable because agents may branch on them.
