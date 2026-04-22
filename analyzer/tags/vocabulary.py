"""Controlled-vocabulary tag registry — single source of truth.

14 axes, ~150 tags. Multi-tag by default unless the axis notes otherwise.
Overlap between axes is intentional: a tag in one axis captures *presence*,
the same concept in another axis captures *role* (e.g. `zoom_punch` is
"was zoom used anywhere" in axis 7, `zoom_punch_in_payoff` is "was zoom the
load-bearing beat" in axis 4). Gemini's schema rejects off-vocabulary tags,
so the only risk is miscategorization — addressed by keeping tag
descriptions concrete and anchored to channel examples where possible.

Adding a tag: append a Tag(...) to the relevant axis and bump the
schema_version in the orchestrator if downstream consumers need to
re-analyze. The Gemini schema auto-rebuilds from this file on next run.
"""

from __future__ import annotations

from typing import Tuple

from analyzer.tags.types import Tag, TagAxis


# ── Axis 1: Title Mechanics ───────────────────────────────────────────────
# How the title tries to earn the click. Multi-tag.
TITLE_MECHANICS = TagAxis(
    field="title_mechanics",
    label="Title mechanics",
    description="How the title tries to earn the click. Multi-tag.",
    multi=True,
    tags=(
        Tag("incredulous_question", "Title poses a shocked question — 'HE HID IT WHERE?!'"),
        Tag("declarative_event", "Title states something happened — 'THE FLOOR JUST ATE ME!'"),
        Tag("hyperbolic_reaction", "First-person exaggerated reaction — 'My Soul LEFT My Body'"),
        Tag("ironic_understatement", "Deliberately muted given the video's content — 'He's probably fine'"),
        Tag("curiosity_gap_ellipsis", "Trails off to create intrigue — 'My Friend Had ONE Job...'"),
        Tag("pop_culture_quote", "Quotes a widely-known line — 'That's No Moon'"),
        Tag("superlative_claim", "Claims best/worst/darkest/#1 — 'PEAK FNAF GAMEPLAY'"),
        Tag("direct_address_imperative", "Command or question aimed at the viewer/subject — 'DON'T TOUCH ME'"),
        Tag("all_caps_intensity", "Majority uppercase for volume. Pairs with most other mechanics."),
        Tag("lowercase_casual", "Deliberately lowercase/casual — 'i miss among us'"),
        Tag("emoji_amplifier", "Title contains an emoji used for emphasis (😂 😱 🤯 etc.)"),
        Tag("game_title_named", "Game franchise explicitly in title — 'FNAF', 'Elden Ring'"),
        Tag("franchise_character_named", "Specific character named — 'Freddy', 'Voldemort baby'"),
        Tag("number_or_specific_claim", "Specific number or unit in title — 'Died in 3 SECONDS'"),
        Tag("parenthetical_aside", "Adds a parenthetical beat — '(jumpscare)', '(Gross)'"),
        Tag("repetition_for_effect", "Phrase repeated in the title itself — 'PERFECT WHITE TEETH PERFECT WHITE TEETH...'"),
        Tag("self_deprecation", "Streamer makes themselves the butt — '(I deserved that)'"),
        Tag("cliffhanger_promise", "Promises a bigger payoff than stated — '...THEN THIS!'"),
        Tag("quoted_dialogue_title", "Title is a direct quote of in-video speech — '\"RES US\".... oops'"),
    ),
)


# ── Axis 2: Title ↔ Video Relationship ────────────────────────────────────
# How the title frames what actually happens on screen. Multi-tag.
TITLE_VIDEO_RELATIONSHIP = TagAxis(
    field="title_video_relationship",
    label="Title ↔ video relationship",
    description="How the title frames what happens in the video. Multi-tag.",
    multi=True,
    tags=(
        Tag("title_creates_question", "Title poses a question the video answers."),
        Tag("title_spoils_payoff", "Title gives away the punchline; click is for how, not what."),
        Tag("title_is_quote_from_video", "Title quotes a line literally said in the video."),
        Tag("title_misdirects", "Title implies one thing; video delivers a different but related beat."),
        Tag("title_undersells_content", "Title is calmer/smaller than what the video shows."),
        Tag("title_oversells_content", "Title promises more than the video delivers."),
    ),
)


# ── Axis 3: Hook Type ─────────────────────────────────────────────────────
# What's happening in the opening seconds that stops the scroll. Multi-tag.
HOOK_TYPE = TagAxis(
    field="hook_type",
    label="Hook type",
    description="Opening-seconds strategy. Multi-tag.",
    multi=True,
    tags=(
        Tag("visual_anomaly_observation", "Streamer notices something off in the game world."),
        Tag("in_medias_res_chaos", "Dropped straight into ongoing chaos or action."),
        Tag("verbal_setup_buildup", "Streamer narrates, building to a reveal."),
        Tag("jumpscare_tension", "Known horror setup — viewer knows a scare is coming."),
        Tag("cold_open_stillness", "Deliberate quiet/stillness before disruption."),
        Tag("reaction_first_frame", "Streamer's face/scream/yell is the opening beat."),
        Tag("chat_or_challenge_driven", "Chat message or external prompt kicks off the clip."),
        Tag("absurd_premise_intro", "Weird/impossible claim stated upfront the video must justify."),
        Tag("title_card_text_open", "Video opens with big on-screen text explaining the beat."),
        Tag("face_cam_introduction", "Streamer's facecam is visible from the first frame."),
        Tag("confession_or_admission", "'I'll be honest...' / 'I did something bad...' opener."),
        Tag("direct_challenge_to_viewer", "'Watch this' / 'you won't believe' aimed at the audience."),
        Tag("midsentence_start", "Clip begins mid-word/mid-sentence to feel live/unedited."),
    ),
)


# ── Axis 4: Payoff Technique ──────────────────────────────────────────────
# How the payoff lands. Multi-tag — often stacks.
PAYOFF_TECHNIQUE = TagAxis(
    field="payoff_technique",
    label="Payoff technique",
    description="How the video's payoff lands. Multi-tag.",
    multi=True,
    tags=(
        Tag("rewind_replay", "Video pulls back to re-show the key moment."),
        Tag("smash_cut_to_reference", "Abrupt cut to external footage (film clip, meme cutaway)."),
        Tag("meme_audio_punctuation", "External meme audio carries the comic beat."),
        Tag("callback_to_hook", "Payoff explicitly references the opening."),
        Tag("escalation_to_absurd", "Situation ramps past logic before the beat lands."),
        Tag("delayed_punchline", "Long setup, one payoff beat at the end."),
        Tag("twist_reversal", "Expected outcome flips."),
        Tag("multiple_failure_cascade", "Repeated failures compound — death loop, juggling."),
        Tag("genuine_reaction_peak", "Real unscripted shock/laugh IS the payoff."),
        Tag("audio_sting_reveal", "Punchline is a sound effect (boom, record scratch)."),
        Tag("freeze_frame_isolation", "Freeze on the key moment for emphasis."),
        Tag("zoom_punch_in_payoff", "Rapid zoom IS the payoff beat (not just a flourish)."),
        Tag("slow_motion_beat", "Slow-mo marks the critical moment."),
        Tag("on_screen_text_reveal", "Text overlay is the payoff, not a cut."),
        Tag("joke_repetition_rule_of_three", "Same beat hits three times for comic effect."),
        Tag("comedic_silence_beat", "The laugh is the silence after something happens."),
        Tag("cut_to_black_ending", "Video ends abruptly on the beat, no outro."),
        Tag("ironic_calm_after_chaos", "Loud/chaotic then suddenly calm or normal."),
    ),
)


# ── Axis 5: Audio Elements Present ────────────────────────────────────────
# Presence flags for audio. Overlapping is expected and desired: a video with
# a meme audio clip that contains a record-scratch SFX gets BOTH
# `has_meme_audio_clip` and `has_sound_effect_stingers`. Multi-tag.
AUDIO_ELEMENTS = TagAxis(
    field="audio_elements",
    label="Audio elements present",
    description="Presence flags for audio. Multi-tag — stacking is expected.",
    multi=True,
    tags=(
        Tag("has_raw_game_audio", "Unedited in-game sound is present in the mix."),
        Tag("has_streamer_vo_commentary", "Streamer commentary audible over the clip."),
        Tag("has_streamer_scream_or_yell", "Streamer screams, yells, or loud vocal reaction."),
        Tag("has_meme_audio_clip", "Recognizable meme sound/audio clip is present."),
        Tag("has_popular_music_snippet", "Identifiable popular song used rhythmically."),
        Tag("has_original_music_or_score", "Original/incidental music bed (not a meme or pop track)."),
        Tag("has_sound_effect_stingers", "Punctuating SFX — boom, record scratch, ding, swoosh."),
        Tag("has_silence_beat", "Deliberate silence used as a beat somewhere in the clip."),
        Tag("has_tts_voices", "Text-to-speech voices present (chat TTS, character TTS)."),
        Tag("has_chat_readback", "Chat messages read aloud or shown to drive audio."),
        Tag("has_character_impression", "Streamer voices a character impression."),
        Tag("has_laughter_track", "Real or layered laughter present in audio."),
        Tag("has_bleep_censor", "Profanity bleeped or censored audibly."),
    ),
)


# ── Axis 6: On-screen Text Style ──────────────────────────────────────────
# How on-screen text is used, if at all. Multi-tag.
ON_SCREEN_TEXT = TagAxis(
    field="on_screen_text_style",
    label="On-screen text style",
    description="How on-screen text is used. Multi-tag.",
    multi=True,
    tags=(
        Tag("no_text_overlay", "No text overlay anywhere in the video."),
        Tag("full_caption_subtitles", "Full dialogue captions throughout."),
        Tag("kinetic_text_animation", "Animated/popping text with motion."),
        Tag("meme_format_text", "Impact-font / classic meme text formatting."),
        Tag("reaction_word_callouts", "Single-word beat text — 'WHAT?!', 'OOPS'."),
        Tag("title_card_intro_text", "Intro card with big text at the start."),
        Tag("end_card_text", "Outro/end card text at the end."),
        Tag("arrow_or_annotation_overlays", "Arrows or annotations pointing at things in frame."),
    ),
)


# ── Axis 7: Visual Effects / Editing ──────────────────────────────────────
# Presence flags for visual effects. Distinct from axis 4 payoff tags:
# these are "was this effect used anywhere" vs "was it the load-bearing beat".
# Multi-tag.
VISUAL_EFFECTS = TagAxis(
    field="visual_effects",
    label="Visual effects / editing",
    description="Effects and editing techniques present. Multi-tag.",
    multi=True,
    tags=(
        Tag("zoom_punch", "Sharp zoom-in used somewhere in the edit."),
        Tag("slow_motion_segment", "Slow-motion segment anywhere in the clip."),
        Tag("freeze_frame", "Freeze frame used as a beat or punctuation."),
        Tag("speed_ramp_acceleration", "Speed ramp / fast-forward acceleration."),
        Tag("rewind_effect", "Visual rewind as a transition effect."),
        Tag("shake_on_impact", "Screen shake on hits or impacts."),
        Tag("color_filter_shift", "Color grade or filter change used for emphasis."),
        Tag("split_screen", "Split-screen or side-by-side comparison."),
        Tag("picture_in_picture_facecam", "Facecam in a PiP window over gameplay."),
        Tag("green_screen_overlay", "Green-screen composite (streamer over gameplay)."),
        Tag("zoom_and_enhance_meme", "Pixelated 'zoom and enhance' meme bit."),
        Tag("flashing_cut_montage", "Rapid flashing montage of cuts."),
    ),
)


# ── Axis 8: Cut Density ───────────────────────────────────────────────────
# Overall editing pace. SINGLE-TAG.
CUT_DENSITY = TagAxis(
    field="cut_density",
    label="Cut density",
    description="Overall editing pace. Single-tag — pick the dominant.",
    multi=False,
    tags=(
        Tag("single_take_uncut", "No cuts — continuous take from start to end."),
        Tag("sparse_cuts_1_to_3", "1-3 cuts total across the video."),
        Tag("moderate_cuts_4_to_8", "4-8 cuts."),
        Tag("rapid_montage", "Many cuts, MTV/TikTok-rapid pacing."),
    ),
)


# ── Axis 9: Narrative POV ─────────────────────────────────────────────────
# Whose perspective we watch from. SINGLE-TAG.
NARRATIVE_POV = TagAxis(
    field="narrative_pov",
    label="Narrative POV",
    description="Whose perspective we watch from. Single-tag — pick the dominant.",
    multi=False,
    tags=(
        Tag("first_person_gameplay_only", "Pure first-person gameplay, no facecam."),
        Tag("first_person_with_facecam_pip", "First-person gameplay with facecam PiP."),
        Tag("third_person_observer", "Third-person / observer view of the action."),
        Tag("chat_perspective", "Chat is the narrator / framing device."),
    ),
)


# ── Axis 10: Content Archetype ────────────────────────────────────────────
# What kind of moment this is. Multi-tag.
CONTENT_ARCHETYPE = TagAxis(
    field="content_archetype",
    label="Content archetype",
    description="What kind of moment this is. Multi-tag.",
    multi=True,
    tags=(
        Tag("fail_or_death", "Streamer dies, fails, or messes up."),
        Tag("win_or_clutch", "Skillful or clutch moment."),
        Tag("weird_game_moment", "Game did something odd, broken, or unintended."),
        Tag("scare_reaction", "Jumpscare or horror moment hits the streamer."),
        Tag("funny_npc_behavior", "NPC does something absurd or dumb."),
        Tag("chat_interaction_moment", "Moment driven by chat interaction."),
        Tag("friend_group_chaos", "Multiplayer chaos with friends."),
        Tag("monologue_bit", "Streamer is just talking entertainingly, minimal gameplay beat."),
        Tag("meta_commentary", "About streaming, the game industry, or the medium itself."),
        Tag("game_criticism_or_praise", "Streamer evaluates the game directly (good/bad)."),
        Tag("lore_or_reference_explainer", "Short explains a piece of lore or reference."),
    ),
)


# ── Axis 11: Emotional Tone ───────────────────────────────────────────────
# What the viewer feels. Multi-tag.
EMOTIONAL_TONE = TagAxis(
    field="emotional_tone",
    label="Emotional tone",
    description="What the viewer feels. Multi-tag.",
    multi=True,
    tags=(
        Tag("tension_and_fear", "Viewer feels tension, dread, or fear."),
        Tag("silly_absurdity", "Viewer feels delighted absurdity."),
        Tag("schadenfreude", "Viewer enjoys the streamer's or NPC's misfortune."),
        Tag("wholesome_or_sweet", "Wholesome, warm, or sweet feeling."),
        Tag("rage_or_frustration", "Rage, frustration, or 'tilt' energy."),
        Tag("nostalgic_or_referential", "Nostalgia or reference-driven affection."),
        Tag("edgy_or_dark_humor", "Edgy or dark-humor feel."),
        Tag("genuine_shock", "Honest, uncalculated surprise."),
        Tag("cringe_comedy", "Cringe / awkwardness drives the feeling."),
        Tag("chaotic_energy", "Chaos, everything-at-once, overstimulation as feeling."),
    ),
)


# ── Axis 12: Ending Style ─────────────────────────────────────────────────
# How the video exits. SINGLE-TAG.
ENDING_STYLE = TagAxis(
    field="ending_style",
    label="Ending style",
    description="How the video exits. Single-tag.",
    multi=False,
    tags=(
        Tag("abrupt_cut_to_black", "Hard cut to black, no outro."),
        Tag("punchline_then_fade", "Punchline beat then fade/soft end."),
        Tag("reaction_hold", "Last frame is a reaction face or held yell."),
        Tag("text_outro_card", "Text outro / end card closes the video."),
        Tag("loopable_ending", "Last frame flows back to first — made to loop."),
        Tag("dialogue_tag_closer", "A spoken line is the final beat."),
    ),
)


# ── Axis 13: Horror Mechanics ─────────────────────────────────────────────
# What horror beats the video uses. Applies even to comedy shorts that set
# up horror then undercut it. Multi-tag.
HORROR_MECHANICS = TagAxis(
    field="horror_mechanics",
    label="Horror mechanics",
    description="Horror beats used. Multi-tag. Applies even to comedy shorts that set up then undercut horror.",
    multi=True,
    tags=(
        Tag("jumpscare_payoff", "Sudden reveal / loud hit is the moment."),
        Tag("dread_buildup", "Slow-burn tension; anticipation is the beat."),
        Tag("environmental_unease", "The world feels wrong — lighting, geometry, ambient."),
        Tag("fakeout_gotcha_scare", "Fake scare / bait; payoff is the misdirection."),
        Tag("chase_panic_sequence", "Being actively pursued by something."),
        Tag("isolation_vulnerability", "Alone, cornered, nowhere-to-go framing."),
        Tag("body_horror_or_gore", "Physical grotesque / body-horror imagery."),
        Tag("psychological_or_uncanny", "Things that shouldn't exist or behave this way."),
        Tag("character_reveal_horror", "Antagonist/entity appears — the reveal IS the scare."),
        Tag("lore_reveal_horror", "Understanding what's happening is the scare."),
        Tag("sound_cue_dread", "Audio does the horror work — sting, wrong ambient."),
        Tag("horror_subverted_by_comedy", "Horror setup deliberately undercut — the gag is the breaking of tension."),
    ),
)


# ── Axis 14: Humor Mechanics ──────────────────────────────────────────────
# What comedy techniques are doing work. Multi-tag — beats commonly stack.
HUMOR_MECHANICS = TagAxis(
    field="humor_mechanics",
    label="Humor mechanics",
    description="Comedy techniques at work. Multi-tag.",
    multi=True,
    tags=(
        Tag("slapstick_physical", "Physical comedy — falls, hits, ragdoll, bonks."),
        Tag("reaction_comedy", "The laugh is the streamer's reaction itself."),
        Tag("timing_comedy", "The beat is the joke — perfect cut placement."),
        Tag("absurdist_non_sequitur", "Random/surreal, doesn't need to make sense."),
        Tag("ironic_contrast", "Setup implies X, payoff delivers not-X."),
        Tag("exaggeration_hyperbole", "Overblown reaction for comic effect."),
        Tag("self_deprecating_humor", "Streamer is the butt of the joke."),
        Tag("schadenfreude_humor", "Laughing at someone's misfortune."),
        Tag("dark_comedy_humor", "Morbid premise played for laughs."),
        Tag("cringe_for_laughs", "Awkwardness/embarrassment is the engine."),
        Tag("character_mismatch", "Dissonance — cute thing doing scary, dumb thing outsmarting."),
        Tag("wordplay_or_pun", "Verbal humor / wordplay as the beat."),
        Tag("callback_running_gag", "Joke lands because of prior setup within the video."),
        Tag("fourth_wall_break", "Acknowledging stream/viewer directly."),
        Tag("meta_gaming_humor", "Laughing at game mechanics, bugs, glitches, logic holes."),
        Tag("chat_roast_humor", "Chat jokes, or streamer playing off chat."),
    ),
)


# ── Registry ──────────────────────────────────────────────────────────────

ALL_AXES: Tuple[TagAxis, ...] = (
    TITLE_MECHANICS,
    TITLE_VIDEO_RELATIONSHIP,
    HOOK_TYPE,
    PAYOFF_TECHNIQUE,
    AUDIO_ELEMENTS,
    ON_SCREEN_TEXT,
    VISUAL_EFFECTS,
    CUT_DENSITY,
    NARRATIVE_POV,
    CONTENT_ARCHETYPE,
    EMOTIONAL_TONE,
    ENDING_STYLE,
    HORROR_MECHANICS,
    HUMOR_MECHANICS,
)
