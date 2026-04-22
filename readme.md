# Shorts Analyzer

Standalone tool for analyzing a YouTube channel's top Shorts with Gemini.
Extracted from SimpleAutoSubs as a standalone app with its own API server.

For each Short it:

1. Fetches the channel's videos via the YouTube Data API
2. Filters to Shorts (≤60s) and sorts by view count
3. Downloads the top N via `yt-dlp`
4. Runs each through Gemini for a video description + title-effectiveness analysis
5. Appends results to a JSON file (resumable — already-analyzed videos are skipped)

## Setup

```sh
cd shorts_analyzer
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json
# edit config.json with your API keys
```

You need:
- A **Gemini API key** — https://aistudio.google.com/apikey
- A **YouTube Data API v3 key** — https://console.cloud.google.com/apis/library/youtube.googleapis.com

## Running

### As an API server (recommended)

```sh
python api_server.py
```

Starts on `http://localhost:9021`. Another app can then drive it over HTTP.

### As a library

```python
from analyzer import YouTubeShortAnalyzer

a = YouTubeShortAnalyzer(
    channel_url="https://www.youtube.com/@PeepingOtter/shorts",
    output_file="output/peepingotter.json",
    max_shorts=100,
)
a.process_shorts()
```

## API reference

Base URL: `http://localhost:9021`

| Method | Endpoint | Purpose |
|---|---|---|
| `GET`    | `/health`              | Health check |
| `POST`   | `/analyze/start`       | Start a job |
| `POST`   | `/analyze/stop`        | Request graceful stop (finishes current video) |
| `GET`    | `/analyze/status`      | Current job state + progress |
| `GET`    | `/logs?last=200`       | Recent log lines |
| `DELETE` | `/logs`                | Clear logs |
| `GET`    | `/results`             | List JSON output files |
| `GET`    | `/results/read?name=`  | Read a result file as JSON |
| `GET`    | `/results/download?name=` | Download a result file |
| `DELETE` | `/results/{name}`      | Delete a result file |

### Start a job

```sh
curl -X POST http://localhost:9021/analyze/start \
  -H "Content-Type: application/json" \
  -d '{
    "channel_url": "https://www.youtube.com/@PeepingOtter/shorts",
    "max_shorts": 100
  }'
```

Response:
```json
{
  "ok": true,
  "channel_url": "https://www.youtube.com/@PeepingOtter/shorts",
  "output_filename": "PeepingOtter.json",
  "max_shorts": 100
}
```

If you want to pick the filename yourself, add `"output_filename": "whatever.json"`.

### Poll status

```sh
curl http://localhost:9021/analyze/status
```

```json
{
  "running": true,
  "stop_requested": false,
  "current_job": { "channel_url": "...", "output_path": "...", "started_at": 1234567890 },
  "last_error": null,
  "progress": {
    "phase": "analyzing",
    "current": 12,
    "total": 100,
    "current_title": "Famous Last Words"
  }
}
```

`phase` values: `idle`, `fetching`, `analyzing`, `done`, `error`.

### Stop a running job

```sh
curl -X POST http://localhost:9021/analyze/stop
```

The worker checks the stop flag between videos, so the currently-downloading
video will finish before the worker exits. Results already saved stay on disk.

### Browse results

```sh
curl http://localhost:9021/results
curl "http://localhost:9021/results/read?name=PeepingOtter.json"
```

## Notes

- Results are **resumable**. Start the same job again and it skips videos
  whose `video_id` is already in the output JSON.
- Output files live in `./output/` and are named `<channel-handle>.json` by
  default.
- The `temp_downloads/` directory is cleared after each job.
- Port is hardcoded to **9021** in `api_server.py`. SimpleAutoSubs uses
  9020, so they don't collide.


```python main.py --max 1 --output output/_test_phase23.json```