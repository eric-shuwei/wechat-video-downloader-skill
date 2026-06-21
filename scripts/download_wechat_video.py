#!/usr/bin/env python3
"""Resolve or download a WeChat Channels / 视频号 share link to a local MP4 file."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, unquote, urlparse, urlunparse
from urllib.request import Request, urlopen

DEFAULT_RESOLVER_API = "https://sph.litao.workers.dev/api/fetch_video_profile"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137 Safari/537.36"
)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ResolvedVideo:
    def __init__(self, feed: dict[str, Any]):
        self.feed = feed
        self.feed_info = feed.get("data", {}).get("feedInfo", {})
        self.meta = extract_metadata(feed)
        self.standard_url = pick_standard_url(feed)
        self.raw_url = to_raw_video_url(self.standard_url)

    def option_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "standard",
                "label": "下载视频",
                "description": "网站默认播放/下载版本，通常兼容性更好、文件更小。",
                "available": bool(self.standard_url),
            },
            {
                "id": "raw",
                "label": "下载原始视频",
                "description": "按网站“下载原始视频”逻辑获取，通常质量更高、文件更大。",
                "available": bool(self.raw_url),
            },
        ]

    def selected_url(self, quality: str) -> str:
        if quality == "raw":
            return self.raw_url
        return self.standard_url


def sanitize_filename(value: str, fallback: str = "wechat-video") -> str:
    value = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", value or "").strip(" ._")
    value = re.sub(r"\s+", " ", value)
    value = (value[:120] or fallback).strip(" ._") or fallback
    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = f"{value}_video"
    return value


def fetch_json(api_url: str, share_url: str, timeout: int) -> dict[str, Any]:
    body = json.dumps({"url": share_url}, ensure_ascii=False).encode("utf-8")
    req = Request(
        api_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"resolver API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"resolver API request failed: {exc.reason}") from exc

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("resolver API returned a non-JSON response") from exc

    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))
    if not isinstance(data, dict):
        raise RuntimeError("resolver API returned an unexpected response shape")
    return data


def pick_standard_url(feed: dict[str, Any]) -> str:
    feed_info = feed.get("data", {}).get("feedInfo", {})
    candidates = [
        feed_info.get("h264VideoInfo", {}).get("videoUrl"),
        feed_info.get("h265VideoInfo", {}).get("videoUrl"),
        feed_info.get("videoUrl"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
            return candidate
    raise RuntimeError("no downloadable video URL found in resolver response")


def to_raw_video_url(url: str) -> str:
    """Match the website's 'download raw video' behavior.

    It decodes the selected playback URL and keeps only encfilekey + token.
    """
    try:
        parsed = urlparse(unquote(url))
        query = parse_qs(parsed.query)
        encfilekey = query.get("encfilekey", [""])[0]
        token = query.get("token", [""])[0]
        if encfilekey and token:
            raw_query = urlencode({"encfilekey": encfilekey, "token": token})
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", raw_query, ""))
    except Exception:
        pass
    return url


def extract_metadata(feed: dict[str, Any]) -> dict[str, Any]:
    data = feed.get("data", {})
    feed_info = data.get("feedInfo", {})
    author_info = data.get("authorInfo", {})
    description = feed_info.get("description") or ""
    return {
        "author": author_info.get("nickname") or "",
        "description": description,
        "suggested_filename": sanitize_filename(description or "wechat-video") + ".mp4",
        "stats": {
            "likes": feed_info.get("likeCountFmt") or "",
            "favorites": feed_info.get("favCountFmt") or "",
            "forwards": feed_info.get("forwardCountFmt") or "",
            "comments": feed_info.get("commentCountFmt") or "",
        },
    }


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for idx in range(2, 1000):
        candidate = path.with_name(f"{stem}-{idx}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot allocate a unique output path for {path}")


def is_preview_safe_filename(filename: str) -> bool:
    if not filename.lower().endswith(".mp4"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", filename))


def build_preview_path(output_path: Path) -> Path:
    if is_preview_safe_filename(output_path.name):
        return output_path
    return unique_path(output_path.parent / "wechat_video_preview.mp4")


def ensure_preview_file(output_path: Path) -> Path:
    preview_path = build_preview_path(output_path)
    if preview_path == output_path:
        return output_path
    try:
        os.link(output_path, preview_path)
    except OSError:
        shutil.copy2(output_path, preview_path)
    return preview_path


def download_file(url: str, output_path: Path, timeout: int) -> tuple[int, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "video/mp4,video/*,*/*"})
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")
    try:
        with urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            size = 0
            with tmp_path.open("wb") as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    fh.write(chunk)
            tmp_path.replace(output_path)
            return size, content_type
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"video download HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"video download failed: {exc.reason}") from exc
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def build_output_path(out_dir: Path, filename: str, description: str, quality: str, overwrite: bool) -> Path:
    name = filename or sanitize_filename(description or "wechat-video")
    suffix = Path(name).suffix or ".mp4"
    stem = sanitize_filename(Path(name).stem)
    if quality == "raw" and not filename:
        stem = f"{stem}_raw"
    output_path = out_dir / f"{stem}{suffix}"
    return output_path if overwrite else unique_path(output_path)


def print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve or download a WeChat Channels share URL.")
    parser.add_argument("url", help="WeChat Channels share URL, e.g. https://weixin.qq.com/sph/...")
    parser.add_argument("--info", action="store_true", help="Only resolve metadata and available download choices; do not download")
    parser.add_argument(
        "--quality",
        choices=("standard", "raw"),
        default="standard",
        help="Download choice after user confirmation. standard=下载视频, raw=下载原始视频. Default: standard",
    )
    parser.add_argument("--out-dir", default="outputs", help="Output directory. Default: outputs")
    parser.add_argument("--filename", default="", help="Optional output filename")
    parser.add_argument("--timeout", type=int, default=60, help="Network timeout seconds. Default: 60")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output file")
    parser.add_argument(
        "--resolver-api",
        default=os.environ.get("WECHAT_VIDEO_RESOLVER_API", DEFAULT_RESOLVER_API),
        help="Compatible resolver API endpoint. Can also be set by WECHAT_VIDEO_RESOLVER_API.",
    )
    args = parser.parse_args()

    resolved = ResolvedVideo(fetch_json(args.resolver_api, args.url, timeout=args.timeout))

    if args.info:
        print_json({
            **resolved.meta,
            "choices": resolved.option_summary(),
            "next_step": "Ask the user to choose standard or raw, then rerun with --quality standard or --quality raw.",
        })
        return 0

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = build_output_path(
        out_dir,
        args.filename,
        resolved.meta.get("description", ""),
        args.quality,
        args.overwrite,
    )
    video_url = resolved.selected_url(args.quality)
    size, content_type = download_file(video_url, output_path, timeout=args.timeout)
    if size <= 0:
        raise RuntimeError("downloaded file is empty")

    preview_path = ensure_preview_file(output_path)
    guessed_type = mimetypes.guess_type(output_path.name)[0] or ""
    print_json({
        **resolved.meta,
        "quality": args.quality,
        "quality_label": "下载原始视频" if args.quality == "raw" else "下载视频",
        "output_path": str(output_path),
        "output_path_abs": str(output_path.resolve()),
        "preview_path": str(preview_path),
        "preview_path_abs": str(preview_path.resolve()),
        "size_bytes": size,
        "content_type": content_type or guessed_type,
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
