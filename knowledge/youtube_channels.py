"""Read public channel uploads and timed captions without downloading video media."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .supermemory_captions import caption_source
from .transcripts import youtube_source


def channel_url(value):
    if not isinstance(value, str) or len(value) > 250:
        raise ValueError("Enter a YouTube @handle or channel URL.")
    value = value.strip()
    if value.startswith("@"):
        path = "/" + value
    elif re.fullmatch(r"UC[\w-]{22}", value, re.ASCII):
        path = "/channel/" + value
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or parsed.hostname not in {"youtube.com", "www.youtube.com"} or parsed.username or parsed.port:
            raise ValueError("Use a YouTube @handle or youtube.com/channel/ URL.")
        path = parsed.path.rstrip("/")
    if not re.fullmatch(r"/@[A-Za-z0-9_.-]{3,100}|/channel/UC[A-Za-z0-9_-]{22}", path):
        raise ValueError("Use a channel handle such as @rajshamani, without a video or tab URL.")
    return "https://www.youtube.com" + path


class QuietLogger:
    def debug(self, message):
        pass
    info = warning = error = debug


class YouTube:
    def client(self, **options):
        from yt_dlp import YoutubeDL
        return YoutubeDL({"quiet": True, "no_warnings": True, "logger": QuietLogger(),
                          "socket_timeout": 20, "retries": 1, "extractor_retries": 1,
                          **options})

    def preview(self, value):
        url = channel_url(value)
        with self.client(extract_flat=True, playlistend=5, skip_download=True) as client:
            info = client.extract_info(url + "/videos", download=False)
        channel_id = info.get("channel_id") or info.get("id")
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id or ""):
            raise ValueError("YouTube did not return a channel identity.")
        entries = [self.video(e) for e in (info.get("entries") or []) if e and self.valid_video(e) and not self.is_short(e)]
        return {"id": channel_id, "title": info.get("channel") or info.get("uploader") or info.get("title", value),
                "url": "https://www.youtube.com/channel/" + channel_id,
                "handle": value if value.startswith("@") else url.rsplit("/", 1)[-1],
                "sample": entries[:5], "scope": "Long-form uploads from the Videos tab; Shorts excluded"}

    @staticmethod
    def is_short(entry):
        return entry.get("media_type") == "short" or any(
            "/shorts/" in (entry.get(key) or "") for key in ("url", "webpage_url", "original_url"))

    @staticmethod
    def valid_video(entry):
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", entry.get("id") or ""))

    @staticmethod
    def video(entry):
        return {**youtube_source("https://youtu.be/" + entry["id"]),
                "title": entry.get("title") or entry["id"],
                "unavailable": entry.get("availability") in {"private", "premium_only", "subscriber_only", "needs_auth"}
                               or entry.get("live_status") in {"is_live", "is_upcoming"}}

    def uploads(self, channel_id):
        if not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
            raise ValueError("Invalid channel ID.")
        # The combined UU uploads playlist includes Shorts. Import only the Videos tab.
        url = "https://www.youtube.com/channel/" + channel_id + "/videos"
        with self.client(extract_flat=True, lazy_playlist=True, skip_download=True) as client:
            info = client.extract_info(url, download=False)
            for entry in info.get("entries") or []:
                if entry and self.valid_video(entry) and not self.is_short(entry):
                    yield self.video(entry)

    def captions(self, video_id):
        source = youtube_source("https://youtu.be/" + video_id)
        with self.client(skip_download=True, noplaylist=True) as client:
            info = client.extract_info(source["url"], download=False)
            if info.get("id") != video_id:
                raise ValueError("YouTube returned another video.")
            if self.is_short(info):
                raise ValueError("Shorts are excluded. Add a long-form video instead.")
            if info.get("live_status") in {"is_live", "is_upcoming"}:
                raise ValueError("Live or upcoming video; retry after the recording is available.")
            auto, manual = info.get("automatic_captions") or {}, info.get("subtitles") or {}
            original = [lang for lang in auto if lang.endswith("-orig")]
            native = info.get("language")
            tracks = [(lang, auto[lang]) for lang in original]
            if not tracks:
                # Uploaded subtitles may be authored translations; keep the track label.
                tracks = [(lang, manual[lang]) for lang in sorted(manual, key=lambda l: l != native) if lang != "live_chat"]
            if not tracks and native in auto:
                tracks = [(native, auto[native])]
            for language, formats in tracks:
                track = next((f for f in formats if f.get("ext") == "json3"), None)
                if not track:
                    continue
                import json
                with client.urlopen(track["url"]) as response:
                    body = response.read(8_000_001)
                if len(body) > 8_000_000:
                    raise ValueError("Caption track exceeds the supported size.")
                result = caption_source(info, json.loads(body), language)
                result["caption_kind"] = "automatic" if language in auto and not manual.get(language) else "uploaded"
                result["channel_id"] = info.get("channel_id")
                result["media_type"] = info.get("media_type")
                return result
        raise ValueError("No usable timed captions available. This video needs a transcript before it can be indexed.")


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Preview a YouTube channel without importing it")
    parser.add_argument("channel")
    parser.add_argument("--sample-uploads", action="store_true", help="Also inspect three long-form uploads")
    parser.add_argument("--count-uploads", action="store_true", help="Count uploads from the Videos tab, excluding Shorts, without indexing")
    parser.add_argument("--caption-video", help="Check timed-caption extraction for one video; no upload")
    args = parser.parse_args()
    reader = YouTube()
    result = reader.preview(args.channel)
    if args.sample_uploads:
        from itertools import islice
        result["uploads_sample"] = list(islice(reader.uploads(result["id"]), 3))
    if args.count_uploads:
        videos = {video["id"]: video for video in reader.uploads(result["id"])}
        result["uploads_count"] = len(videos)
        result["unavailable_in_listing"] = sum(bool(v["unavailable"]) for v in videos.values())
        result["captions_checked"] = False
    if args.caption_video:
        source = reader.captions(args.caption_video)
        result["caption_check"] = {"id": source["id"], "language": source["language"], "segments": len(source["segments"])}
    print(json.dumps(result, ensure_ascii=False, indent=2))
