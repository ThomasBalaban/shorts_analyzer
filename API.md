# Shorts Analyzer — HTTP API reference

Reference for driving the analyzer from another app (e.g. an Angular
frontend). This file documents the wire protocol only — what endpoints
exist, what they take, what they return, what errors to expect. For
pipeline concepts (phases, breakout score, tailwind) see [readme.md](readme.md)
and [game_plan.md](game_plan.md).

## Connection

- Base URL: `http://localhost:9021`
- Content type: `application/json` everywhere
- CORS: `*` (open — this is a local-only tool)
- Start the server: `python api_server.py`

## Concurrency model

One job slot. `POST /analyze/start` and every `POST /rerun/*` share the
same slot. If a job is running and you POST another, you get **409 "A
job is already running"**. Poll `/analyze/status` until `running` is
false before starting the next one.

`GET` endpoints are always safe — they read files, never start work.

**Nothing runs automatically.** Every endpoint is an explicit operator
action. There are no startup hooks, no schedulers, no auto-refresh of
stale data. Predicate filters (`model_mismatch`, etc.) are tools the
operator reaches for — they never fire on their own.

---

## Files and identifiers

The analyzer writes one JSON file per channel to `output/`:

- `output/<handle>.json` — the canonical analysis file
- `output/<handle>.context.json` — channel baseline (medians, analytics cache reference)
- `output/<handle>.synthesis.json` — Phase 4 corpus-level synthesis
- `output/<handle>.tailwind.json` — Phase 5 per-video tailwind hypotheses

The API's `output` parameter is always the **base filename** (e.g.
`"PeepingOtter.json"`), not a path. The server resolves sibling files
automatically.

Every per-video record is keyed by `video_id` (YouTube's opaque ID,
e.g. `"alz67J3WPCk"`). Use that as the handle for targeted reruns.

---

## Health

### `GET /health`

```json
{ "status": "ok", "port": 9021, "output_dir": "/abs/path/to/output" }
```

Always 200 if the server is up.

---

## Start a new analysis

### `POST /analyze/start`

Fetch shorts from a channel and run Phases 1 → 2 → (4 → 5 handled by
`main.py`, not the API — see note below). Resumable: already-analyzed
`video_id`s are skipped.

```json
{
  "channel_url": "https://www.youtube.com/@PeepingOtter/shorts",
  "output_filename": "PeepingOtter.json",   // optional, derived from @handle
  "max_shorts": 100
}
```

Response:

```json
{
  "ok": true,
  "channel_url": "...",
  "output_filename": "PeepingOtter.json",
  "max_shorts": 100
}
```

Errors: **400** missing `channel_url`, **409** job already running.

> **Phases 4 and 5 via the API:** `/analyze/start` runs Phase 1 + 2
> only. Synthesis and tailwind run via the dedicated rerun endpoints
> below. The CLI (`python main.py`) wires all five phases together, but
> the API keeps them separate so you can drive each independently.

### `POST /analyze/stop`

Request a graceful stop. The worker finishes the current video before
exiting. Results already saved stay on disk.

```json
{ "ok": true, "message": "Stop requested — will halt after current video." }
```

If nothing is running: `{ "ok": false, "reason": "not_running" }`.

### `GET /analyze/status`

Poll this to watch job progress. Safe to hammer (it's a cheap read of
in-memory state).

```json
{
  "running": true,
  "stop_requested": false,
  "current_job": {
    "kind": "rerun_analysis",
    "started_at": 1776994040.15,
    "output": "PeepingOtter.json",
    "video_ids": ["alz67J3WPCk"],
    "filter": null
  },
  "last_error": null,
  "last_result": null,
  "progress": {
    "phase": "rerun_analysis",
    "current": 0,
    "total": 0,
    "current_title": ""
  }
}
```

`current_job.kind` values: `"analyze"`, `"rerun_analytics"`,
`"rerun_analysis"`, `"rerun_synthesis"`, `"rerun_tailwind"`.

`progress.phase` during a fresh analysis moves through `"fetching"` →
`"analyzing"` → `"done"` or `"error"`. For reruns it starts as the
`kind` label and ends on `"done"` / `"error"` / `"idle"` (stopped).

`last_result` is populated when a rerun job completes successfully. Its
shape depends on the job — see each rerun endpoint below.

---

## Per-video state and predicates

### `GET /videos?output=<file>`

The primary reporting endpoint. Returns every video in the corpus with
per-phase `_meta` stamps and `stale_reasons` — the predicate labels
that would pick that video up in a rerun.

```json
{
  "analysis_file": "/abs/path/to/output/PeepingOtter.json",
  "tailwind_file": "/abs/path/to/output/PeepingOtter.tailwind.json",
  "synthesis_file": "/abs/path/to/output/PeepingOtter.synthesis.json",
  "channel_url": "https://www.youtube.com/@PeepingOtter/shorts",
  "corpus_schema_version": 3,
  "current": {
    "analysis": {
      "model": "gemini-3.1-pro-preview",
      "schema_version": 3,
      "prompt_hash": "9f37e771b742faf9"
    },
    "tailwind": {
      "model": "gemini-3.1-pro-preview",
      "schema_version": 1,
      "prompt_hash": "5d1b2675acb52a25"
    }
  },
  "videos": [
    {
      "video_id": "alz67J3WPCk",
      "title": "MY TOILET",
      "views": 123456,
      "published_date": "2025-12-05",
      "breakout_score": 4.65,
      "phases": {
        "analytics": {
          "present": true,
          "avg_view_percentage": 63.0,
          "fetched_at": "2026-04-22T22:05:00.000000",
          "stale_reasons": []
        },
        "analysis": {
          "present": true,
          "meta": {
            "model": "gemini-3.1-pro-preview",
            "schema_version": 3,
            "prompt_hash": "9f37e771b742faf9",
            "ran_at": "2026-04-22T22:05:00.000000"
          },
          "ran_at": "2026-04-22T22:05:00.000000",
          "stale_reasons": []
        },
        "tailwind": {
          "present": true,
          "meta": { "...": "..." },
          "stale_reasons": []
        }
      }
    }
  ]
}
```

`stale_reasons` values:

- `"missing"` — phase hasn't run for this video yet
- `"schema_mismatch"` — record's `schema_version` ≠ current
- `"model_mismatch"` — record's `model` ≠ current model (legacy records with `model=null` match this too)
- `"prompt_mismatch"` — record's `prompt_hash` ≠ current prompt hash

Empty array = fresh. Use this data to drive a UI that shows which
videos would be affected by each rerun button.

Errors: **404** file not found.

---

## Reruns

All reruns share the same selector contract:

- Send either `video_ids: [...]` (explicit list) OR `filter: "..."` (predicate).
- Sending **both** is a 400.
- Sending **neither** is a 400.
- Unknown filter strings are a 400.

Allowed filter values: `"all"`, `"missing"`, `"schema_mismatch"`,
`"model_mismatch"`, `"prompt_mismatch"`. Not every filter makes sense
for every phase — see each endpoint's notes.

Every rerun is a background job. The endpoint returns immediately with
the job description; you poll `/analyze/status` to watch it finish.

### `POST /rerun/analytics`

Refetch Phase 1 YouTube Analytics for selected videos and update each
record's `analytics` block + `breakout_score`. Rebuilds the channel
baseline from the full corpus (medians stay accurate).

Body:

```json
{
  "output": "PeepingOtter.json",
  "video_ids": ["alz67J3WPCk"],   // OR filter: "missing"
  "filter": null
}
```

Filter notes: only `"all"` and `"missing"` are supported here.
`schema_mismatch`/`model_mismatch`/`prompt_mismatch` don't apply —
analytics has no model or prompt. Use `"missing"` to backfill records
that don't have a retention curve.

`last_result` shape on completion:

```json
{ "targets": 5, "updated": 5, "errors": [] }
```

Errors: **400** bad selector, **404** file not found, **409** job
running, **500** if Analytics OAuth isn't configured.

### `POST /rerun/analysis`

**Expensive.** Each target = one video download + one Gemini Pro
`generate_content` call with `thinking_level=high`. Targeted records
have `gemini_analysis`, `analytics`, `breakout_score`, and
`analysis_timestamp` replaced; untargeted records are untouched.

Body:

```json
{
  "output": "PeepingOtter.json",
  "video_ids": null,
  "filter": "model_mismatch"
}
```

Guardrail: `filter: "all"` is **refused** (400) to prevent accidental
full-corpus reruns. To rerun everything, send explicit `video_ids`.

`last_result`:

```json
{
  "targets": 12,
  "updated": 11,
  "errors": [
    { "video_id": "abc123", "error": "Video processing failed" }
  ]
}
```

Common usage:
- Single bad record: `{ "video_ids": ["abc123"] }`
- Post model upgrade: `{ "filter": "model_mismatch" }`
- Post prompt iteration: `{ "filter": "prompt_mismatch" }`
- Post schema bump: `{ "filter": "schema_mismatch" }`
- Backfill records where Phase 2 never ran: `{ "filter": "missing" }`

Errors: **400** bad selector / `filter=all`, **404** file not found,
**409** job running.

### `POST /rerun/synthesis`

Cheap text-only Gemini call over the whole corpus. No per-video
selector — always corpus-wide.

Body:

```json
{
  "output": "PeepingOtter.json",
  "skip_narrative": false
}
```

`skip_narrative: true` computes the stats tables but skips the Gemini
prose layer — useful when iterating on the math.

`last_result`: `{ "ok": true }`. The written file is
`output/<base>.synthesis.json`.

Errors: **404** file not found, **409** job running.

### `POST /rerun/tailwind`

Cheap text-only Gemini call per candidate. Merges into the existing
`<base>.tailwind.json` — untargeted entries are preserved.

Body:

```json
{
  "output": "PeepingOtter.json",
  "video_ids": ["alz67J3WPCk"],   // OR filter: "..."
  "filter": null,
  "include_all": false,
  "use_trends": false
}
```

Omitting both `video_ids` and `filter` runs the default tailwind sweep
over candidates that pass the residual cutoffs (same as `python
tailwind.py --analysis ...`). `include_all: true` bypasses those
cutoffs and processes every short. `use_trends: true` validates each
hypothesis against Google Trends (requires `pip install pytrends`; if
missing, the run proceeds without Trends and logs a warning).

`last_result` on targeted run:

```json
{ "targets": 3, "updated": 3 }
```

On default / `include_all` run: `{ "targets": null, "updated": null }`
(the tailwind file itself carries the full record).

Errors: **400** bad selector, **404** file not found, **409** job running.

---

## Logs

### `GET /logs?last=200`

Tail of recent log lines from the running or most-recent job.

```json
{ "lines": ["[21:27:45] ...", "[21:27:46] ..."] }
```

### `DELETE /logs`

Clear the in-memory buffer. Returns `{ "ok": true }`.

---

## Result files (raw JSON)

### `GET /results`

List analyzer output files.

```json
{
  "files": [
    {
      "name": "PeepingOtter.json",
      "path": "/abs/path/output/PeepingOtter.json",
      "modified": 1776994040.15,
      "size": 70204
    }
  ],
  "dir": "/abs/path/output"
}
```

### `GET /results/read?name=<file>`

Return the file contents as JSON.

### `GET /results/download?name=<file>`

Same file as a download attachment (`Content-Disposition`).

### `DELETE /results/{name}`

Delete a result file. Returns `{ "ok": true, "deleted": "<file>" }`.

All three reject names containing `/`, `\`, or `..` (400).

---

## Error conventions

- **400** Bad request (missing/invalid body, bad selector, bad filename)
- **404** File not found
- **409** Job already running
- **500** Unhandled server error (see `last_error` in `/analyze/status`)

Error bodies always look like `{ "detail": "message" }`.

---

## Typical UI flows

### "Refresh analytics for everything missing a retention curve"

1. `GET /videos?output=PeepingOtter.json` → find videos where
   `phases.analytics.present === false`.
2. `POST /rerun/analytics` with `{ "filter": "missing" }` (or an
   explicit `video_ids` list you built client-side).
3. Poll `GET /analyze/status` until `running === false`.
4. `GET /videos?...` again to confirm `stale_reasons === []`.

### "A new Gemini model shipped and I want to re-analyze everything on the old one"

1. `GET /videos?output=...` → UI shows which videos have
   `phases.analysis.stale_reasons.includes("model_mismatch")`.
2. User confirms (this is expensive — full video upload + Pro + thinking=high per record).
3. `POST /rerun/analysis` with `{ "filter": "model_mismatch" }`.
4. Poll. Watch `progress.current / progress.total` for per-video updates.

### "One record came back garbled"

1. User clicks the bad row in a `/videos` listing.
2. `POST /rerun/analysis` with `{ "video_ids": ["<id>"] }`.
3. Poll, then re-fetch `/results/read?name=...` to show the new analysis.

### "Rebuild the strategy doc for a downstream app"

1. Make sure per-video records are current (see above flows).
2. `POST /rerun/synthesis` with `{ "skip_narrative": false }`.
3. After completion, `GET /results/read?name=<base>.synthesis.json`.
4. Repeat `POST /rerun/tailwind` (no body selector → default sweep) if
   residual estimates changed.

---

## Angular client sketch

Rough shape — adapt to your HTTP client of choice:

```ts
interface VideoPhaseState {
  present: boolean;
  meta?: { model: string | null; schema_version: number; prompt_hash: string | null; ran_at: string } | null;
  stale_reasons: Array<'missing' | 'schema_mismatch' | 'model_mismatch' | 'prompt_mismatch'>;
}

interface VideoRow {
  video_id: string;
  title: string;
  views: number;
  published_date: string;
  breakout_score: number | null;
  phases: {
    analytics: VideoPhaseState & { avg_view_percentage: number | null; fetched_at: string | null };
    analysis:  VideoPhaseState & { ran_at: string | null };
    tailwind:  VideoPhaseState;
  };
}

interface VideosResponse {
  channel_url: string;
  current: {
    analysis: { model: string; schema_version: number; prompt_hash: string };
    tailwind: { model: string; schema_version: number; prompt_hash: string };
  };
  videos: VideoRow[];
}

type RerunFilter = 'all' | 'missing' | 'schema_mismatch' | 'model_mismatch' | 'prompt_mismatch';

interface RerunBody {
  output: string;
  video_ids?: string[];
  filter?: RerunFilter;
}
```

Poll `/analyze/status` on an interval (e.g. 1s while a job is running,
back off when idle). `running: false` + `progress.phase === 'done'` is
the success signal; `progress.phase === 'error'` with `last_error`
populated is the failure signal.
