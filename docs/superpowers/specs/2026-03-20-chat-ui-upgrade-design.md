# Chat UI Upgrade — Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Goal:** Upgrade the chat tab in task detail to match best-in-class AI chat UIs (Claude.ai, ChatGPT, Gemini). Markdown rendering, code blocks with syntax highlighting, proper message layout, streaming cursor, auto-resize input, tool use visualization.

---

## What Changes

Only the **Chat tab** inside `task-detail.html` and supporting JS. No backend changes. No new endpoints.

---

## Features

### 1. Markdown Rendering

Use **marked.js** (CDN, 7KB gzipped) for client-side markdown-to-HTML conversion.

**Render these elements:**
- Headers (h1-h3) — scaled relative sizes
- Bold, italic, inline code
- Bullet and numbered lists
- Links (open in new tab)
- Blockquotes
- Horizontal rules

**When to render:** After message is complete (not during streaming). During streaming, show raw text. On stream end, apply `marked.parse()` to the full message.

### 2. Code Blocks with Syntax Highlighting

Use **highlight.js** (CDN) with a dark theme (github-dark or similar).

**Code block anatomy:**
```
┌──────────────────────────────────────┐
│ python                    [Copy]     │  ← header bar
├──────────────────────────────────────┤
│ def hello():                         │
│     print("Hello, world!")           │  ← highlighted code
│                                      │
└──────────────────────────────────────┘
```

- Header bar: language label (left) + Copy button (right)
- Dark background (`#0d1117`) regardless of theme
- Copy button: `navigator.clipboard.writeText()`, shows "Copied!" for 1.5s
- Font: monospace, 13px, line-height 1.5
- Border-radius: 8px
- Padding: 16px

### 3. Message Layout

**User messages:**
- Label "you" in `--text-muted`, 11px
- Content: `--text-primary`, 14px, line-height 1.6
- Bottom margin: 24px

**Agent messages:**
- Label "agent" in `--accent-text`, 11px
- Content: `--text-primary`, 14px, line-height 1.6, rendered markdown
- Bottom margin: 24px

No bubbles. Full-width blocks. Visual differentiation via labels only.

### 4. Streaming

- During streaming: append raw text character-by-character (existing typewriter)
- Show blinking cursor `|` at end of streaming text (CSS animation)
- On stream complete: replace raw text with `marked.parse()` output + `hljs.highlightAll()`
- Auto-scroll: keep latest content visible, stop if user scrolls up

### 5. Thinking Indicator

Replace current simple text with shimmer effect:
```html
<div class="thinking-shimmer">
  <span class="typing-dot"></span>
  <span class="typing-dot"></span>
  <span class="typing-dot"></span>
</div>
```
Three pulsing dots with staggered delay.

### 6. Tool Use Visualization

When agent uses a tool, render as a collapsible card:
```
▶ Edit  src/auth/timeout.ts
```
Click to expand and see tool details/result. Color-coded left border by tool type.

This already exists in the activity feed — reuse the same pattern in chat.

### 7. Input Area

- Auto-resize textarea (CSS grid trick) — grows up to 6 lines, then scrolls
- Enter = send, Shift+Enter = newline
- Placeholder: "Send a message..."
- Disable during generation, show "Stop" button instead

### 8. Stop Button

During generation, replace the send affordance with a Stop button that cancels the WebSocket connection.

---

## CDN Dependencies (add to base.html or task-detail.html)

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css">
```

---

## CSS Additions (in styles.css)

```css
/* Chat message rendering */
.chat-msg { margin-bottom: 24px; }
.chat-msg-label { font-size: 11px; margin-bottom: 4px; }
.chat-msg-content { font-size: 14px; line-height: 1.6; color: var(--text-primary); }
.chat-msg-content p { margin: 0 0 12px; }
.chat-msg-content ul, .chat-msg-content ol { margin: 0 0 12px; padding-left: 20px; }
.chat-msg-content h1, .chat-msg-content h2, .chat-msg-content h3 {
  font-weight: 700; margin: 16px 0 8px; color: var(--text-primary);
}
.chat-msg-content h1 { font-size: 1.3em; }
.chat-msg-content h2 { font-size: 1.15em; }
.chat-msg-content h3 { font-size: 1.05em; }
.chat-msg-content code:not(pre code) {
  background: var(--bg-chrome); padding: 2px 6px; border-radius: 4px;
  font-size: 0.9em; font-family: 'SF Mono', 'Fira Code', monospace;
}
.chat-msg-content blockquote {
  border-left: 3px solid var(--separator-strong); padding-left: 12px;
  color: var(--text-secondary); margin: 0 0 12px;
}
.chat-msg-content a { color: var(--accent-text); text-decoration: none; }
.chat-msg-content a:hover { text-decoration: underline; }

/* Code blocks */
.chat-msg-content pre { margin: 0 0 12px; border-radius: 8px; overflow: hidden; }
.code-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; background: #161b22; font-size: 12px; color: #7d8590;
}
.code-header button {
  background: transparent; border: 1px solid #30363d; color: #7d8590;
  padding: 2px 10px; border-radius: 4px; font-size: 11px; cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}
.code-header button:hover { color: #e6edf3; border-color: #555; }
.chat-msg-content pre code {
  display: block; padding: 16px; font-size: 13px; line-height: 1.5;
  font-family: 'SF Mono', 'Fira Code', monospace; overflow-x: auto;
}

/* Streaming cursor */
.streaming::after {
  content: ''; display: inline-block; width: 2px; height: 1em;
  background: var(--accent-text); margin-left: 2px; vertical-align: text-bottom;
  animation: blink 1s step-end infinite;
}
@keyframes blink { 50% { opacity: 0; } }

/* Thinking dots */
.thinking-dots { display: flex; align-items: center; gap: 4px; padding: 8px 0; }
.typing-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent-text);
  animation: dot-pulse 1.4s infinite ease-in-out;
}
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* Auto-resize textarea */
.grow-wrap { display: grid; }
.grow-wrap::after {
  content: attr(data-replicated-value) " ";
  white-space: pre-wrap; visibility: hidden;
  grid-area: 1 / 1 / 2 / 2; font: inherit; padding: inherit;
}
.grow-wrap > textarea {
  grid-area: 1 / 1 / 2 / 2; resize: none; overflow: hidden;
  max-height: 150px;
}
```

---

## Files to Modify

- `src/agents/static/styles.css` — add chat CSS classes above
- `src/agents/templates/task-detail.html` — update chat tab HTML
- `src/agents/static/task-detail.js` — rewrite chat rendering with marked.js + hljs
- `src/agents/templates/base.html` — add marked.js and highlight.js CDN links

---

## Out of Scope

- Artifacts/side panel
- File upload
- Voice input
- Chat branching
- Canvas/split-pane editing
