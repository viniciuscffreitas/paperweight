"""Tests for Chat UI Upgrade — markdown rendering, code blocks, streaming cursor.

Covers:
- base.html: CDN links for marked.js and highlight.js
- styles.css: chat CSS classes presence
- task-detail.html: upgraded chat input structure (textarea, grow-wrap, send area)
- task-detail.js: new chat functions present (appendChatMessage, showThinking,
  hideThinking, sendChatPrompt, stopGeneration, addCodeBlockHeaders,
  renderToolCallInChat, loadChatHistory)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.app_state import AppState
from agents.budget import BudgetManager
from agents.config import BudgetConfig, ExecutionConfig, GlobalConfig
from agents.dashboard_html import setup_dashboard
from agents.executor import Executor
from agents.history import HistoryDB
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.task_store import TaskStore

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"
_STATIC_DIR = Path(__file__).parent.parent / "src" / "agents" / "static"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_task(tmp_path):
    app = FastAPI()
    history = HistoryDB(tmp_path / "history.db")
    project_store = ProjectStore(tmp_path / "projects.db")
    task_store = TaskStore(tmp_path / "tasks.db")
    budget = BudgetManager(config=BudgetConfig(), history=history)
    notifier = Notifier(webhook_url="")
    executor = Executor(
        config=ExecutionConfig(),
        budget=budget,
        history=history,
        notifier=notifier,
        data_dir=tmp_path,
    )
    project_store.create_project(id="proj1", name="Proj One", repo_path=str(tmp_path))
    item = task_store.create(
        project="proj1",
        title="Chat test task",
        description="desc",
        source="manual",
    )
    state = AppState(
        projects={},
        executor=executor,
        history=history,
        budget=budget,
        notifier=notifier,
        github_secret="",
        linear_secret="",
        project_store=project_store,
        task_store=task_store,
    )
    setup_dashboard(app, state, GlobalConfig())
    client = TestClient(app)
    client._task_id = item.id
    return client


# ---------------------------------------------------------------------------
# base.html — CDN links
# ---------------------------------------------------------------------------


def _read_base_html() -> str:
    return (_TEMPLATES_DIR / "base.html").read_text()


def test_base_html_has_marked_cdn():
    """base.html must include marked.js CDN for markdown rendering."""
    html = _read_base_html()
    assert "cdn.jsdelivr.net/npm/marked" in html


def test_base_html_has_highlight_js_cdn():
    """base.html must include highlight.js CDN for syntax highlighting."""
    html = _read_base_html()
    assert "highlightjs/cdn-release" in html
    assert "highlight.min.js" in html


def test_base_html_has_highlight_css():
    """base.html must include highlight.js github-dark stylesheet."""
    html = _read_base_html()
    assert "github-dark.min.css" in html


def test_base_html_cdn_scripts_are_deferred():
    """CDN scripts must use defer attribute to avoid blocking render."""
    html = _read_base_html()
    # Both marked and highlight CDN script tags must have defer
    import re

    scripts = re.findall(r'<script[^>]+src="[^"]*(?:marked|highlight\.min)[^"]*"[^>]*>', html)
    assert len(scripts) >= 2, "Expected at least 2 CDN script tags"
    for script in scripts:
        assert "defer" in script, f"Script missing defer: {script}"


# ---------------------------------------------------------------------------
# styles.css — chat CSS classes
# ---------------------------------------------------------------------------


def _read_css() -> str:
    return (_STATIC_DIR / "styles.css").read_text()


def test_css_has_chat_msg_class():
    """styles.css must define .chat-msg for message wrapper."""
    assert ".chat-msg {" in _read_css() or ".chat-msg{" in _read_css()


def test_css_has_chat_msg_label_classes():
    """styles.css must define .chat-msg-label.user and .chat-msg-label.agent."""
    css = _read_css()
    assert ".chat-msg-label" in css
    assert ".chat-msg-label.agent" in css


def test_css_has_chat_msg_content_class():
    """styles.css must define .chat-msg-content with markdown-aware styles."""
    css = _read_css()
    assert ".chat-msg-content" in css


def test_css_has_code_header_class():
    """styles.css must define .code-header for code block headers."""
    assert ".code-header" in _read_css()


def test_css_has_streaming_cursor():
    """styles.css must define .streaming::after for animated cursor."""
    css = _read_css()
    assert ".streaming::after" in css
    assert "cursor-blink" in css


def test_css_has_thinking_dots():
    """styles.css must define .thinking-dots and .typing-dot for animated indicator."""
    css = _read_css()
    assert ".thinking-dots" in css
    assert ".typing-dot" in css
    assert "dot-pulse" in css


def test_css_has_grow_wrap():
    """styles.css must define .grow-wrap for auto-resize textarea."""
    assert ".grow-wrap" in _read_css()


def test_css_has_tool_call_classes():
    """styles.css must define .tool-call, .tool-call-header, .tool-call-detail."""
    css = _read_css()
    assert ".tool-call {" in css or ".tool-call{" in css
    assert ".tool-call-header" in css
    assert ".tool-call-detail" in css


def test_css_tool_call_expanded_state():
    """styles.css must define .tool-call.expanded to show detail on toggle."""
    css = _read_css()
    assert ".tool-call.expanded .tool-call-detail" in css
    assert ".tool-call.expanded .arrow" in css


# ---------------------------------------------------------------------------
# task-detail.html — chat tab structure
# ---------------------------------------------------------------------------


def test_task_detail_has_chat_textarea(client_with_task):
    """Chat input must be a <textarea> (not <input>) for multiline support."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert r.status_code == 200
    assert b'<textarea id="chat-input"' in r.content


def test_task_detail_chat_textarea_has_grow_wrap(client_with_task):
    """Chat textarea must be inside .grow-wrap for auto-resize."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert b'class="grow-wrap"' in r.content


def test_task_detail_chat_has_send_button(client_with_task):
    """Chat area must have a Send button calling sendChatPrompt()."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert b"sendChatPrompt" in r.content
    assert b'id="chat-send-btn"' in r.content


def test_task_detail_chat_has_send_area(client_with_task):
    """Chat must have id='chat-send-area' for Stop/Send button swapping."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert b'id="chat-send-area"' in r.content


def test_task_detail_chat_textarea_shift_enter_hint(client_with_task):
    """Chat input area must show Shift+Enter hint for new line."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert b"Shift+Enter" in r.content


def test_task_detail_chat_messages_container(client_with_task):
    """chat-messages div must exist for message rendering."""
    task_id = client_with_task._task_id
    r = client_with_task.get(f"/hub/proj1/task/{task_id}")
    assert b'id="chat-messages"' in r.content


# ---------------------------------------------------------------------------
# task-detail.js — function presence
# ---------------------------------------------------------------------------


def _read_task_detail_js() -> str:
    # task-detail.js and chat.js are companion modules that share global scope.
    # Tests check the combined surface — functions may live in either file.
    return (
        (_STATIC_DIR / "task-detail.js").read_text() + "\n" + (_STATIC_DIR / "chat.js").read_text() + "\n" + (_STATIC_DIR / "chat-multimodal.js").read_text()
    )


def test_js_has_append_chat_message_with_streaming_param():
    """appendChatMessage must accept isStreaming and optional attachments parameters."""
    js = _read_task_detail_js()
    assert "function appendChatMessage(container, role, text, isStreaming, attachments, timestamp)" in js


def test_js_has_add_code_block_headers():
    """addCodeBlockHeaders function must exist for copy button injection."""
    assert "function addCodeBlockHeaders(container)" in _read_task_detail_js()


def test_js_has_render_tool_call_in_chat():
    """renderToolCallInChat function must exist for inline tool cards."""
    assert "function renderToolCallInChat(container, event)" in _read_task_detail_js()


def test_js_has_stop_generation():
    """stopGeneration function must exist for Stop button."""
    assert "function stopGeneration()" in _read_task_detail_js()


def test_js_show_thinking_uses_dots():
    """showThinking must create animated dots, not toggle #thinking-indicator."""
    js = _read_task_detail_js()
    assert "function showThinking()" in js
    assert "thinking-dots" in js
    assert "typing-dot" in js


def test_js_hide_thinking_removes_element():
    """hideThinking must remove the _thinkingEl DOM element."""
    js = _read_task_detail_js()
    assert "function hideThinking()" in js
    assert "_thinkingEl" in js
    assert "removeChild" in js


def test_js_load_chat_history_handles_tool_use():
    """loadChatHistory must render tool_use events via renderToolCallInChat."""
    js = _read_task_detail_js()
    assert "function loadChatHistory(events)" in js
    assert "renderToolCallInChat" in js


def test_js_send_chat_prompt_shows_stop_button():
    """sendChatPrompt must swap in a Stop button during generation."""
    js = _read_task_detail_js()
    assert "stopGeneration" in js
    assert "chat-send-area" in js
    assert "origHTML" in js


def test_js_send_chat_prompt_finalizes_markdown():
    """sendChatPrompt stream-complete handler must apply marked.parse."""
    js = _read_task_detail_js()
    assert "marked.parse" in js
    assert "streaming" in js
    assert "classList.remove" in js


def test_js_append_chat_message_uses_css_classes():
    """appendChatMessage must use CSS classes, not inline styles."""
    js = _read_task_detail_js()
    assert "chat-msg" in js
    assert "chat-msg-content" in js
    assert "chat-msg-label" in js
    # Must not fall back to raw inline style for the message wrapper
    assert "wrapper.className" in js


def test_js_thinking_el_variable_declared():
    """_thinkingEl must be declared at module level for shared state."""
    js = _read_task_detail_js()
    assert "var _thinkingEl = null" in js


def test_js_checks_marked_defined_before_use():
    """appendChatMessage must guard marked usage with typeof check."""
    js = _read_task_detail_js()
    assert "typeof marked !== 'undefined'" in js


def test_js_checks_hljs_defined_before_use():
    """Syntax highlighting must guard hljs usage with typeof check."""
    js = _read_task_detail_js()
    assert "typeof hljs !== 'undefined'" in js
