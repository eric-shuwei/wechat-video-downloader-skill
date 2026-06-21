---
name: wechat-video-downloader-skill
description: Use when a user provides a WeChat Channels / 视频号 share URL such as https://weixin.qq.com/sph/... and wants to choose between the website-style video download options, then save the selected video locally as an MP4.
metadata:
  short-description: Download WeChat Channels videos locally
---

# WeChat Video Downloader

Resolve a WeChat Channels / 视频号 share link, ask the user which website-style download option they want, then download the selected MP4 locally.

## When to use

Use this skill when the user provides a WeChat Channels share URL and asks to download, save, preview, display, or return the video.

Typical input:

```text
https://weixin.qq.com/sph/...
```

## Agent workflow

1. Locate this skill directory: the directory containing this `SKILL.md` file.
2. First resolve metadata only; do not download yet:

   ```bash
   python3 /path/to/wechat-video-downloader-skill/scripts/download_wechat_video.py 'WECHAT_CHANNELS_URL' --info
   ```

3. Read stdout JSON. Use `description`, `author`, and `choices` to ask the user which option to download.
4. Ask exactly one concise choice question:

   ```text
   解析到了这个视频：{description}
   你要下载哪个版本？
   1. 下载视频：网站默认版本，通常兼容性更好、文件更小
   2. 下载原始视频：按网站“下载原始视频”逻辑获取，通常质量更高、文件更大
   ```

5. After the user chooses, download the selected option:

   ```bash
   # 用户选择“下载视频”
   python3 /path/to/wechat-video-downloader-skill/scripts/download_wechat_video.py 'WECHAT_CHANNELS_URL' --quality standard --out-dir outputs

   # 用户选择“下载原始视频”
   python3 /path/to/wechat-video-downloader-skill/scripts/download_wechat_video.py 'WECHAT_CHANNELS_URL' --quality raw --out-dir outputs
   ```

6. Read stdout JSON. Use `preview_path_abs` for media preview when present; otherwise use `output_path_abs`.
7. Verify the file exists and is non-empty. If `ffprobe` is available, optionally inspect duration/codecs.
8. Return the local MP4 to the user. In Codex Desktop, always embed the video with an absolute-path Markdown media tag:

   ```md
   ![视频预览](/absolute/path/to/video.mp4)
   ```

   Use `preview_path_abs` for the embed when present. Do not use `file://` links as the primary result.

## CLI contract

The script requires only Python 3 standard library modules.

Resolve choices without downloading:

```bash
python3 scripts/download_wechat_video.py 'https://weixin.qq.com/sph/...' --info
```

Download after user confirmation:

```bash
python3 scripts/download_wechat_video.py 'https://weixin.qq.com/sph/...' --quality standard --out-dir outputs
python3 scripts/download_wechat_video.py 'https://weixin.qq.com/sph/...' --quality raw --out-dir outputs
```

Useful options:

```bash
--info             Resolve metadata and choices only; do not download
--quality VALUE    standard or raw. Default: standard
--out-dir DIR      Output directory. Default: outputs
--filename NAME    Optional output filename
--timeout SECONDS  Network timeout. Default: 60
--overwrite        Replace an existing output file
```

Successful `--info` output is JSON like:

```json
{
  "author": "...",
  "description": "...",
  "suggested_filename": "example.mp4",
  "choices": [
    {"id": "standard", "label": "下载视频", "available": true},
    {"id": "raw", "label": "下载原始视频", "available": true}
  ]
}
```

Successful download output is JSON like:

```json
{
  "quality": "raw",
  "quality_label": "下载原始视频",
  "output_path": "outputs/example_raw.mp4",
  "output_path_abs": "/absolute/path/outputs/example_raw.mp4",
  "preview_path": "outputs/example_raw.mp4",
  "preview_path_abs": "/absolute/path/outputs/example_raw.mp4",
  "size_bytes": 123456,
  "content_type": "video/mp4"
}
```

## Final response style

Use a terse result-only response by default.

Success response shape for Codex Desktop:

```text
已下载完成：{filename}（{size}，MP4，{resolution}，时长 {duration}）。

![视频预览](/absolute/path/to/preview-safe-video.mp4)

文件路径：`/absolute/path/to/preview-safe-video.mp4`
```

Use `preview_path_abs` from the script output for the Markdown embed when present. The script creates a short preview-safe MP4 copy when the original filename may break Markdown rendering.

Failure response shape:

```text
下载失败：{concise_error}
```

## Behavior rules

- Do not download before asking the user to choose between `standard` and `raw`, unless the user already specified a version.
- Do not add extra explanations unless the user explicitly asks how the skill works.
- Keep intermediate resolver/media details out of the user-facing response.
- Save user-facing video files under `outputs/` by default when the current environment has such a convention.
- For Codex Desktop, use `preview_path_abs` and embed it with `![视频预览](/absolute/path.mp4)` in the final response.
- If download or parsing fails, report the concise error and ask for a fresh share link only when the error suggests expiry or invalid input.
- Only download user-provided public or authorized content. Do not help bypass paywalls, DRM, private access, or platform restrictions.

## Portability notes

- Works for Codex, Claude Code, Cursor, and other file-based agents that can read `SKILL.md` and execute local scripts.
- Does not depend on agent-specific installation paths.
- The resolver endpoint can be overridden with `WECHAT_VIDEO_RESOLVER_API` if a maintainer wants to route requests through another compatible service.
