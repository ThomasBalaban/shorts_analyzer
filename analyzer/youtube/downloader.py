"""
yt-dlp wrapper for downloading individual Shorts.

Single responsibility: given a YouTube URL and a video ID, put an MP4 on
disk and return the path. No analysis, no API calls.
"""

from pathlib import Path
from typing import Callable, Optional

import yt_dlp  # type: ignore


class ShortDownloader:
    def __init__(
        self,
        temp_dir: Path,
        log_func: Optional[Callable[[str], None]] = None,
    ):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        self.log_func = log_func or print

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def download(self, video_url: str, video_id: str) -> Path:
        output_path = self.temp_dir / f"{video_id}.mp4"
        ydl_opts = {
            "format": "best[ext=mp4]",
            "outtmpl": str(output_path),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            return output_path
        except Exception as e:
            self._log(f"Error downloading video {video_id}: {e}")
            raise

    def cleanup(self) -> None:
        """Wipe the temp download directory."""
        if self.temp_dir.exists():
            for file in self.temp_dir.glob("*"):
                try:
                    file.unlink()
                except Exception:
                    pass
