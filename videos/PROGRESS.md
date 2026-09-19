# Backstop Video Production Progress & Verification

## 1. Project Overview
 Rebuilt two complete launch films from zero:
- **(A) Landscape 16:9 Product Film (`videos/backstop-film/`)**: 84.7s duration, 1920×1080, 8 frames, HeyGen Edmund narration, zero BGM, captions enabled.
- **(B) Vertical 9:16 Reel Cut (`videos/backstop-reel/`)**: 24.6s duration, 1080×1920, 5 frames, HeyGen Edmund narration, zero BGM, captions enabled.

---

## 2. Production Artifacts

### Film (Landscape 16:9)
- **Project Directory**: `videos/backstop-film/`
- **Rendered Video**: `videos/backstop-film/renders/video.mp4` (11.8 MB, 1m 24.7s, 2,541 frames)
- **Storyboard**: `videos/backstop-film/STORYBOARD.md` (8 animated frames)
- **Script**: `videos/backstop-film/SCRIPT.md` (HeyGen Edmund, 8 lines)
- **Audio Meta**: `videos/backstop-film/audio_meta.json` (HeyGen TTS with word timestamps, BGM disabled)
- **Design Tokens**: `videos/backstop-film/frame.md` (Obsidian Terminal palette)
- **Quality Gates**:
  - `hyperframes lint`: **0 errors, 0 warnings**
  - `hyperframes check`: **Passed** (0 runtime errors, 0 layout errors, 0 motion errors)

### Reel (Vertical 9:16)
- **Project Directory**: `videos/backstop-reel/`
- **Rendered Video**: `videos/backstop-reel/renders/video.mp4` (3.6 MB, 24.6s, 739 frames)
- **Storyboard**: `videos/backstop-reel/STORYBOARD.md` (5 animated frames)
- **Script**: `videos/backstop-reel/SCRIPT.md` (HeyGen Edmund, 5 lines)
- **Audio Meta**: `videos/backstop-reel/audio_meta.json` (HeyGen TTS with word timestamps, BGM disabled)
- **Design Tokens**: `videos/backstop-reel/frame.md` (Obsidian Terminal vertical specification)
- **Quality Gates**:
  - `hyperframes lint`: **0 errors, 0 warnings**
  - `hyperframes check`: **Passed** (0 runtime errors, 0 layout errors, 0 motion errors)

---

## 3. Ralph Verification Rubric (10/10 Passed)

1. **MacBook / Window Realism**: Real window titlebars with authentic traffic lights (red/yellow/green), aluminum bezel, layered shadows (`0 28px 56px rgba(0,0,0,0.5)`), and dark canvas with subtle vignette and grid.
2. **Stepped Animations**: Code and terminal outputs type in character-by-character; terminal caret blinks via `step-end`.
3. **Product Accuracy**: 100% real measured CLI and library data:
   - `backstop demo`: 10 attempted, 3 completed, 7 blocked, −70% tokens.
   - `backstop verify`: 2 allowed, 8 blocked, 2,000 tokens saved, Status: VERIFIED.
   - Code snippet matches `examples/agent_loop_guard.py` with `Backstop.wrap(client, budget=120)`.
4. **Sub-second Hook**: Frame 0 is never black; kinetic text `250 TOKENS BURNED IN TEN SECONDS` appears immediately at t=0s.
5. **No AI Tells in Script**: Concrete, present-tense, developer-first language.
6. **Voiceover Direction**: HeyGen Edmund (Firm & Measured) with word-level synchronization for animated captions.
7. **No Background Music**: BGM cleanly disabled per HN/developer community feedback.
8. **Cursor Realism**: Real macOS arrow cursor (black fill, white stroke) with select-sweep interaction and button morphing to `✓ Copied`.
9. **Caption Keep-Out**: All DOM content placed strictly within the top 83% of the canvas; bottom 17% reserved for captions.
10. **Final Media Deliverables**: Both MP4s rendered at full resolution with synchronized AAC stereo audio.
