"""Tests for multimodal chat — image attachment upload endpoint and UI elements.

Covers:
- POST /api/uploads: saves base64 image, returns path
- POST /api/uploads: rejects missing data
- task-detail.html: attach button and voice button present
- task-detail.html: chat-attachment-strip and file input present
- styles.css: multimodal CSS classes present
- task-detail.js: multimodal functions present
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.agent_routes import register_agent_routes
from agents.app_state import AppState
from agents.budget import BudgetManager
from agents.config import BudgetConfig, ExecutionConfig, GlobalConfig
from agents.dashboard_html import setup_dashboard
from agents.executor import Executor
from agents.history import HistoryDB
from agents.notifier import Notifier
from agents.project_store import ProjectStore
from agents.session_manager import SessionManager
from agents.task_store import TaskStore

_TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "agents" / "templates"
_STATIC_DIR = Path(__file__).parent.parent / "src" / "agents" / "static"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(tmp_path):
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
    session_manager = SessionManager(tmp_path / "sessions.db")
    project_store.create_project(id="proj1", name="Proj One", repo_path=str(tmp_path))
    item = task_store.create(
        project="proj1",
        title="Multimodal test task",
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
        session_manager=session_manager,
    )
    cfg = GlobalConfig()
    setup_dashboard(app, state, cfg)
    register_agent_routes(app, state, cfg)
    client = TestClient(app)
    client._task_id = item.id
    return client


# ---------------------------------------------------------------------------
# /api/uploads — backend endpoint
# ---------------------------------------------------------------------------


def test_upload_endpoint_saves_file(app_client, tmp_path, monkeypatch):
    """POST /api/uploads with valid base64 PNG must save file and return path."""
    # 1x1 transparent PNG, base64-encoded
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    # Use monkeypatch to redirect uploads to tmp_path so we don't litter /tmp
    tmp_path / "uploads"

    Path("/tmp/paperweight_uploads")
    # Patch by making the endpoint use our tmp dir via environment or direct mock
    # Since the endpoint hardcodes the path, patch Path inside the module call
    # by monkeypatching the Path constructor used there.
    # Simplest: just call it and verify the file appears in /tmp/paperweight_uploads
    r = app_client.post(
        "/api/uploads",
        json={"data": png_b64, "mime_type": "image/png"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "path" in body
    assert body["path"].endswith(".png")
    assert "filename" in body
    # File must actually exist
    assert Path(body["path"]).exists()


def test_upload_endpoint_missing_data(app_client):
    """POST /api/uploads without data must return 400."""
    r = app_client.post("/api/uploads", json={"mime_type": "image/png"})
    assert r.status_code == 400


def test_upload_endpoint_jpeg_extension(app_client):
    """POST /api/uploads with jpeg mime type must save as .jpg."""
    # Minimal JPEG marker bytes (valid enough for base64 decode)
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 12 + b"\xff\xd9"
    jpeg_b64 = base64.b64encode(jpeg_bytes).decode()
    r = app_client.post(
        "/api/uploads",
        json={"data": jpeg_b64, "mime_type": "image/jpeg"},
    )
    assert r.status_code == 200
    assert r.json()["path"].endswith(".jpg")


def test_upload_endpoint_accepts_data_url_prefix(app_client):
    """POST /api/uploads with data:image/png;base64,... prefix must strip it."""
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    data_url = f"data:image/png;base64,{png_b64}"
    r = app_client.post(
        "/api/uploads",
        json={"data": data_url, "mime_type": "image/png"},
    )
    assert r.status_code == 200
    assert Path(r.json()["path"]).exists()


# ---------------------------------------------------------------------------
# task-detail.html — multimodal UI elements
# ---------------------------------------------------------------------------


def test_html_has_attach_button(app_client):
    """Chat input area must have an attach-file button."""
    task_id = app_client._task_id
    r = app_client.get(f"/hub/proj1/task/{task_id}")
    assert r.status_code == 200
    assert b'id="chat-attach-btn"' in r.content


def test_html_has_voice_button(app_client):
    """Chat input area must have a push-to-talk voice button."""
    task_id = app_client._task_id
    r = app_client.get(f"/hub/proj1/task/{task_id}")
    assert b'id="chat-voice-btn"' in r.content


def test_html_has_file_input(app_client):
    """Chat area must have a hidden file input accepting images."""
    task_id = app_client._task_id
    r = app_client.get(f"/hub/proj1/task/{task_id}")
    assert b'id="chat-file-input"' in r.content
    assert b'accept="image/*"' in r.content


def test_html_has_attachment_strip(app_client):
    """Chat area must have the attachment preview strip div."""
    task_id = app_client._task_id
    r = app_client.get(f"/hub/proj1/task/{task_id}")
    assert b'id="chat-attachment-strip"' in r.content


# ---------------------------------------------------------------------------
# styles.css — multimodal CSS classes
# ---------------------------------------------------------------------------


def _read_css() -> str:
    return (_STATIC_DIR / "styles.css").read_text()


def test_css_has_attachment_thumb():
    """styles.css must define .attachment-thumb for image previews."""
    assert ".attachment-thumb" in _read_css()


def test_css_has_attachment_strip():
    """styles.css must define #chat-attachment-strip."""
    assert "#chat-attachment-strip" in _read_css()


def test_css_has_voice_recording_state():
    """styles.css must define #chat-voice-btn.recording with pulse animation."""
    css = _read_css()
    assert "#chat-voice-btn.recording" in css
    assert "voice-pulse" in css


def test_css_has_drag_over_state():
    """styles.css must define #chat-content.drag-over visual feedback."""
    assert "drag-over" in _read_css()


def test_css_has_chat_msg_img():
    """styles.css must define .chat-msg-img for images in chat messages."""
    assert ".chat-msg-img" in _read_css()


def test_css_has_chat_icon_btn():
    """styles.css must define .chat-icon-btn for toolbar icon buttons."""
    assert ".chat-icon-btn" in _read_css()


# ---------------------------------------------------------------------------
# task-detail.js — multimodal functions
# ---------------------------------------------------------------------------


def _read_js() -> str:
    # task-detail.js and chat.js are companion modules that share global scope.
    # Tests check the combined surface — functions may live in either file.
    return (
        (_STATIC_DIR / "task-detail.js").read_text() + "\n" + (_STATIC_DIR / "chat.js").read_text() + "\n" + (_STATIC_DIR / "chat-multimodal.js").read_text()
    )


def test_js_has_init_multimodal():
    """task-detail.js must define initMultimodal() for setup."""
    assert "function initMultimodal()" in _read_js()


def test_js_has_add_attachment_file():
    """task-detail.js must define addAttachmentFile(file) for image handling."""
    assert "function addAttachmentFile(file)" in _read_js()


def test_js_has_render_attachment_strip():
    """task-detail.js must define renderAttachmentStrip() for preview UI."""
    assert "function renderAttachmentStrip()" in _read_js()


def test_js_has_handle_file_input():
    """task-detail.js must define handleFileInput(input) for file picker."""
    assert "function handleFileInput(input)" in _read_js()


def test_js_has_start_voice():
    """task-detail.js must define startVoice() for push-to-talk."""
    assert "function startVoice()" in _read_js()


def test_js_has_stop_voice():
    """task-detail.js must define stopVoice() for push-to-talk release."""
    assert "function stopVoice()" in _read_js()


def test_js_multimodal_state_variables():
    """task-detail.js must declare multimodal state at module level."""
    js = _read_js()
    assert "var _chatAttachments = []" in js
    assert "var _voiceActive = false" in js


def test_js_send_chat_prompt_clears_attachments():
    """sendChatPrompt must clear _chatAttachments after building the prompt."""
    js = _read_js()
    assert "_chatAttachments = []" in js
    assert "renderAttachmentStrip" in js


def test_js_uses_speech_recognition_api():
    """startVoice must use SpeechRecognition / webkitSpeechRecognition."""
    js = _read_js()
    assert "SpeechRecognition" in js
    assert "webkitSpeechRecognition" in js


def test_js_voice_uses_interim_results():
    """Voice recognition must use interimResults for live preview."""
    assert "interimResults = true" in _read_js()
