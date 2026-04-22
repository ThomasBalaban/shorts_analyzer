"""
YouTube Analytics API client (OAuth-based).

Pulls private channel performance data: retention curves and basic
engagement stats (views, watch time, avg view percentage).

NOTE: impressions, CTR, and traffic source breakdown require either
the yt-analytics-monetary.readonly scope (monetized channels only) or
Content Owner API access (MCN-level). Both have been removed — they
will 400 on a standard channel regardless of credentials.

OAuth setup (one-time):
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth 2.0 Client ID (Desktop app type)
  3. Download the JSON and save it as client_secrets.json in the project root
  4. Enable the "YouTube Analytics API" in your project
  5. On first run a browser window opens for authorization
  6. Token is cached at data/analytics_cache/token.json for future runs

Retention note: the Analytics API returns retention at ~5% video-length
intervals (not second-by-second). A 60-second Short gives ~20 data points.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


_SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]


class YouTubeAnalyticsClient:
    def __init__(
        self,
        client_secrets_path: Path,
        token_path: Path,
        log_func: Optional[Callable[[str], None]] = None,
    ):
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)
        self.log_func = log_func or print
        self._service = None

    def _log(self, msg: str) -> None:
        self.log_func(msg)

    def _get_service(self):
        if self._service:
            return self._service

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_path), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                self._log("Refreshing Analytics OAuth token...")
                creds.refresh(Request())
            else:
                if not self.client_secrets_path.exists():
                    raise FileNotFoundError(
                        f"client_secrets.json not found at "
                        f"{self.client_secrets_path}. "
                        "See analytics.py docstring for setup instructions."
                    )
                self._log(
                    "Opening browser for YouTube Analytics authorization..."
                )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secrets_path), _SCOPES)
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json())

        self._service = build("youtubeAnalytics", "v2", credentials=creds)
        return self._service

    def _query(self, **kwargs) -> dict:
        return self._get_service().reports().query(**kwargs).execute()

    def get_video_analytics(
        self, video_id: str, published_date: str
    ) -> dict:
        """
        Fetch analytics data for a single video.

        published_date: YYYY-MM-DD string (used as the query startDate so we
        capture the full lifetime of the video from day one).

        Returns a normalized dict ready for JSON caching:
        {
            video_id, fetched_at,
            views, avg_view_percentage, estimated_minutes_watched,
            retention_curve: [{pct: int, watch_ratio: float}, ...],
        }
        All values are None if the API returned no data for that metric.

        NOTE: impressions, CTR, and traffic_sources are intentionally omitted.
        These require monetization-level or Content Owner API access and will
        400 on a standard channel.
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        base = dict(
            ids="channel==MINE",
            startDate=published_date,
            endDate=end_date,
            filters=f"video=={video_id}",
        )

        result: dict = {
            "video_id": video_id,
            "fetched_at": datetime.now().isoformat(),
        }

        # ── Basic engagement stats ─────────────────────────────────────────
        try:
            resp = self._query(
                **base,
                metrics="views,estimatedMinutesWatched,averageViewPercentage",
            )
            row = (resp.get("rows") or [[None, None, None]])[0]
            result["views"] = int(row[0]) if row[0] is not None else None
            result["estimated_minutes_watched"] = (
                round(float(row[1]), 2) if row[1] is not None else None)
            result["avg_view_percentage"] = (
                round(float(row[2]), 2) if row[2] is not None else None)
        except HttpError as e:
            self._log(f"  Basic stats unavailable for {video_id}: {e}")
            result["views"] = None
            result["estimated_minutes_watched"] = None
            result["avg_view_percentage"] = None

        # ── Retention curve — one data point per ~5% of video length ──────
        try:
            resp = self._query(
                **base,
                metrics="audienceWatchRatio",
                dimensions="elapsedVideoTimeRatio",
            )
            rows = resp.get("rows") or []
            result["retention_curve"] = [
                {
                    "pct": round(float(r[0]) * 100),
                    "watch_ratio": round(float(r[1]), 3),
                }
                for r in sorted(rows, key=lambda r: float(r[0]))
            ]
        except HttpError as e:
            self._log(f"  Retention curve unavailable for {video_id}: {e}")
            result["retention_curve"] = None

        return result