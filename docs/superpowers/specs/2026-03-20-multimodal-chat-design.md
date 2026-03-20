# Multimodal Chat — Screenshot Paste/Drop + Push-to-Talk Voice

**Date**: 2026-03-20
**Status**: Approved
**Task**: `multimodal-chat` in `projects/paperweight.yaml`

## Problem

The paperweight dashboard chat is text-only. Users cannot share screenshots or use voice input, forcing context switching to external tools. Claude Code CLI in `-p` mode has no native image flag, and voice is unsupported entirely.

## Solution

Add two zero-friction input modalities to the existing chat UI:

1. **Screenshot paste & drag-drop** — images saved to worktree, paths injected into prompt for Claude's `Read` tool (which is multimodal)
2. **Push-to-talk voice** — Web Speech API transcribes to text in the textarea, user reviews and sends normally

## Architecture

```
[Browser]                       [Backend]                     [Claude CLI]
  |                                 |                              |
  +- paste/drop image ----+        |                              |
  +- push-to-talk -> STT  |        |                              |
  |                        v        |                              |
  +- POST {prompt, images[]} ----> agent_routes.py:               |
  |                                 1. save images to tempdir      |
  |                                 2. enrich prompt with paths    |
  |                                 3. call run_adhoc(prompt) ---> claude -p "..."
  |                                                                |
  |                                                           Read(img.png)
```

**Key decision**: `agent_routes.py` enriches the prompt and saves images.
`executor.py` remains unchanged — receives a plain text prompt as today.

## Frontend Changes

### Screenshot (task-detail.js)

- `paste` event on `#chat-input` parent: extract `clipboardData.files`
- Accept only `image/png`, `image/jpeg`, `image/gif`, `image/webp` (matches Claude Read tool support)
- `dragover`/`drop` on chat container: accept image files, visual feedback (dashed accent border)
- Inline thumbnail preview below textarea, "x" to remove, stack multiple horizontally
- Client-side resize: max 1600px longest side via canvas. Re-encode as JPEG 85% quality (smaller payloads). If original is PNG with transparency, keep PNG.
- Max 5 images per message. Total payload target < 5MB.
- On send: images included as `base64` array in POST body

### Voice (task-detail.js)

- Microphone button next to Send button
- `SpeechRecognition` API with `lang: navigator.language || 'pt-BR'`
- `mousedown` on mic button = start recording, button pulses red
- `mouseup` = stop, transcription inserted into textarea
- No keyboard shortcut (avoids Space/textarea conflicts)
- Graceful degradation: button hidden if `window.SpeechRecognition` unavailable

## Backend Changes

### agent_routes.py only (executor unchanged)

Request model:
```python
class AgentPromptRequest(BaseModel):
    prompt: str
    model: str = "claude-sonnet-4-6"
    session_id: str | None = None
    max_cost_usd: float = 2.0
    images: list[str] | None = None  # base64 data URIs
```

Image handling flow:
1. Validate `images` count (max 5) and decode each base64 string
2. Validate magic bytes (PNG/JPEG/GIF/WebP header) — reject invalid with 400
3. Save to `{data_dir}/uploads/{run_id}/img-{uuid}.{ext}`
   - **NOT in worktree** — worktree may not exist yet for new sessions
   - Saved to data_dir which always exists
4. Enrich prompt before passing to `run_adhoc`:
   ```
   [In this message, the user shared {n} screenshot(s). Analyze using the Read tool:
   - {path1}
   - {path2}]

   {original prompt}
   ```
5. Pass enriched prompt string to `run_adhoc` — no signature change needed

Cleanup: image directories are ephemeral. A periodic cleanup job or TTL-based removal (>24h) handles orphaned uploads.

## What Does NOT Change

- WebSocket streaming protocol
- Markdown rendering
- Session management
- `executor.py` interface and implementation
- Claude CLI invocation method (`-p` flag)
- No new backend dependencies for MVP (magic-byte validation uses stdlib `struct`)

## Edge Cases

| Case | Handling |
|------|----------|
| Paste plain text | Normal behavior, no interception |
| Image > 10MB | Client-side resize before encode |
| No Web Speech API | Hide mic button |
| Multiple images (>5) | Frontend rejects, shows message |
| Speech not recognized | Visual feedback, textarea unchanged |
| Malformed base64 | Backend returns 400 |
| Invalid file (not image) | Magic byte check rejects, 400 |
| New session (no worktree) | Images saved to data_dir, not worktree |
| Resumed session | Prompt prefix works ("In this message...") |
| Reverse proxy body limit | Document: configure to >=5MB if proxied |

## Testing

- **Unit (backend)**: Pydantic model validation, base64 decode + magic byte check, prompt enrichment logic, file save to data_dir
- **Unit (frontend)**: mock paste/drop events with File objects, mock SpeechRecognition start/stop/result
- **Integration**: POST with/without images returns correct response, files exist on disk after request
- **E2E**: image saved → CLI receives enriched prompt → Read tool can open the file
