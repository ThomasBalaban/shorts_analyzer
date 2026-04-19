# Shorts Analyzer — Hard Update Game Plan

## Goals

Build a single-channel creative intelligence layer that produces a **queryable, evidence-backed corpus** of short-form video analysis — structured for consumption by downstream AIs that write titles and guide edits, not just for human reading.

The analyzer stops being a case-study library and becomes **creative infrastructure**. Specifically, it should make three downstream capabilities possible that are impossible with the current output:

1. **Structural matching** — given a new short, find the past shorts most like it and surface what differentiated the breakouts from the mediocre performers.
2. **Evidence-grounded title and edit advice** — recommendations tied to concrete data (retention curves, traffic sources, views-vs-baseline) instead of Gemini's vibes.
3. **Pattern extraction across the corpus** — channel-wide rules like *"your breakouts share these 7 traits; your median shorts share these 5; these 3 traits are unique to breakouts."*

The hard constraint: this tool is for one channel (mine). We are not building a general system. That lets us use YouTube Analytics (OAuth'd to the channel), bake in my own context, and skip all abstractions that exist to handle the multi-creator case.

---

## What we need to accomplish

The work breaks into four layers, each depending on the one before it:

### Layer 1 — Ground truth from Analytics
Pull real performance data per short so every claim Gemini makes becomes falsifiable against actual viewer behavior.

- Channel baseline normalized **against the channel at the time of publish** (not against today's channel) — a 2022 breakout should be measured against 2022's median, not 2026's
- Retention curves per video (second-by-second % of viewers still watching)
- Traffic source breakdown (Shorts feed vs. subscribers vs. external vs. browse vs. search)
- Impressions and CTR where available
- Views-over-time trajectory, or at least "views after N days"

This layer reshapes *which videos we study hardest*. Sorting by raw view count is lying to us — it overweights older videos and undercounts real outliers on smaller historical baselines.

### Layer 2 — Richer per-video analysis, grounded in Layer 1
Rewrite the Gemini analysis to consume Layer 1 data as input and produce attribution that references it.

- Retention curve fed into the prompt so Gemini has to explain drop-off moments and rewatch spikes
- Traffic-source breakdown fed in so Gemini can distinguish "algorithm loved this" from "audience loved this" from "Reddit sent it"
- New attribution schema that decomposes performance into **replicable craft** / **borrowed equity** / **channel-specific equity** / **probable external tailwind**, each with evidence and confidence level
- Keep the existing rich prose (video description, hook analysis, what-could-be-better) — add tags alongside, don't replace

### Layer 3 — Tag vocabulary for queryability
Structure the output so a downstream AI can aggregate across records without re-reading everything with its own LLM.

- Controlled vocabulary for title mechanics (`quote_reference`, `question_hook`, `delayed_punchline`, `curiosity_gap`, `declarative_claim`, etc.)
- Controlled vocabulary for hook types (`visual_anomaly`, `verbal_setup`, `in_medias_res`, `pattern_interrupt`, etc.)
- Controlled vocabulary for pivot/payoff techniques (`meme_audio_rewind`, `smash_cut_to_source`, `callback_to_hook`, etc.)
- Controlled vocabulary for audio strategy (`meme_audio`, `original_vo`, `music_only`, `silent_cold_open`, etc.)
- Every per-video record gets both prose *and* tags; tags enable queries, prose gives context

The vocabulary has to be small enough to be consistent (Gemini will hallucinate tags if we let it freelance) and large enough to capture real distinctions. This is the most design-sensitive layer — the vocabulary *is* the product.

### Layer 4 — Channel-level synthesis
The layer that turns 100 individual records into actual learning. Generated after enough per-video records exist (probably ≥20).

- What patterns recur across the top quintile (breakouts)
- What patterns recur across the bottom quintile (misses)
- What patterns appear in *both* (baseline channel traits, not causal signals)
- What patterns are **unique to breakouts** — the load-bearing stuff
- Borrowed-equity half-life tracking — which references/audios worked in a time window vs. which are evergreen on this channel
- Conditional patterns: *"when payoff is X, title mechanic Y outperforms Z"*

This is the file that downstream apps actually read at generation time. Individual records are for drill-down; synthesis is for strategy.

---

## General gameplan

Built in dependency order. Each phase is a coherent unit that produces something usable on its own — we're never half-done with a concept, we're done with the concept at that layer and can pause or redirect.

### Phase 1 — Analytics integration and baseline
*Plumbing first, because it gates everything else.*

Wire up YouTube Analytics API (OAuth, not API key — it's your own channel so this is fine). Build a client that pulls per-video retention, traffic sources, impressions, CTR, and the channel's monthly-median short performance.

Store this as its own cache layer — the analyzer fetches from cache, not from Analytics on every run, so we're not rate-limiting ourselves during iteration.

Rework the "top shorts" selection to use **breakout score** (views ÷ channel median at time of publish) as a secondary sort alongside raw views, so we can analyze both "biggest videos" and "biggest outliers."

Deliverable: a `channel_context.json` that contains the baseline data, plus a per-video enrichment dict ready to feed into the analyzer.

### Phase 2 — Prompt and schema rewrite, grounded in Analytics data
*The analyzer starts using the new data immediately, even before we've built the synthesis layer.*

Rewrite the Gemini prompt to receive retention curves and traffic sources as input. The prompt forces Gemini to explain drop-off moments, attribute views to their real source, and produce structured attribution with confidence levels.

Expand the response schema to include the attribution object (replicable craft / borrowed equity / channel-specific / tailwind) and a `_evidence` field per claim that references Analytics data.

Leave tags out of this phase. Get the evidence-grounded prose working first.

Deliverable: per-video JSON records that are measurably more honest than the current ones — Gemini's claims now cite retention spikes and traffic sources.

### Phase 3 — Design and apply the tag vocabulary
*The design work matters more than the code here. Rushing this wastes all the downstream value.*

Before any code: enumerate the tag vocabulary by hand. Look at ~20 already-analyzed shorts and draft the controlled vocabulary across title mechanics, hook types, pivot/payoff techniques, and audio strategies. Keep it tight — when in doubt, combine, don't split.

Then add tags to the Gemini schema with the vocabulary baked into the enum values (so Gemini literally cannot freelance — the schema rejects off-vocabulary tags).

Retro-tag existing analyzed shorts in a single batch pass so we don't have a mixed corpus.

Deliverable: every record has both prose and structured tags. The corpus is now queryable.

### Phase 4 — Channel-level synthesis
*Once the per-video layer is queryable, the synthesis layer writes itself — mostly.*

Build a synthesis module that runs across all analyzed shorts and produces:
- Tag frequency tables split by performance quintile
- "Unique to breakouts" pattern extraction (tags that are significantly overrepresented in the top quintile vs. channel average)
- Conditional pattern detection (when tag A appears, tag B correlates with Nx higher breakout score)
- A Gemini-written narrative layer on top of the stats that reads the patterns and explains them in prose for downstream AI consumption

Output is a separate `channel_synthesis.json` that the downstream apps load *first* for strategy, before drilling into individual records for examples.

Deliverable: the file that actually gets pasted into downstream app system prompts.

### Phase 5 — Tailwind, last and honest
*Saved for last because it's the most speculative and benefits from all the grounding above.*

Now that we know *which* videos really broke out (baseline-normalized) and *what* Analytics can explain (traffic sources), we can scope the tailwind question down to: "for the residual performance Analytics can't account for, what external cultural context was plausibly at play?"

Add a dated-context field where Gemini speculates about cultural tailwinds with an explicit confidence level and reasoning. Optionally wire Google Trends for high-value terms it identifies. Downstream apps treat tailwind claims as hypotheses, not facts.

Deliverable: the final piece that explains residual variance, honestly flagged as speculation where it is speculation.

---

## What we deliberately are NOT doing

- Making this work for channels other than mine. Every simplification that falls out of the single-channel assumption is a simplification we take.
- Building a UI. The output is JSON for other apps to consume.
- Real-time analysis. Runs are batch, probably overnight when the channel has new shorts worth adding.
- Replacing the existing per-video rich prose. We're adding structure alongside, not replacing the human-readable analysis.
- Trying to predict future trends. The tool studies the past to inform the present. Prediction is a downstream concern.

---

## Order of attack (TL;DR)

1. **Analytics integration + baseline normalization** — reshapes what we study
2. **Evidence-grounded prompt rewrite** — makes Gemini's attribution falsifiable
3. **Tag vocabulary + structured schema** — makes the corpus queryable
4. **Channel-level synthesis** — turns records into patterns
5. **Tailwind analysis** — fills the residue, honestly

Each phase is independently useful. If we stop after Phase 2, we have a much better per-video analyzer. If we stop after Phase 3, we have a queryable corpus. Phase 4 is where the real downstream value compounds. Phase 5 is the honest ceiling.