"""Agent session API route registration."""
import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Response

from agents.app_state import AppState
from agents.config import GlobalConfig
from agents.executor_utils import generate_run_id

logger = logging.getLogger(__name__)


def _build_session_history(session_id: str, state: AppState) -> str:
    """Build a conversation summary from session events for model-switch context injection."""
    runs = state.history.list_runs_by_session(session_id)
    if not runs:
        return ""
    header = "[Previous conversation — you are continuing where another model left off]"
    lines = [header + "\n"]
    for run in runs:
        if run.trigger_type == "agent" and run.task:
            lines.append(f"User: {run.task}")
        events = state.history.list_events(run.id)
        assistant_text = []
        for ev in events:
            if ev.get("type") == "assistant" and ev.get("content"):
                assistant_text.append(ev["content"])
        if assistant_text:
            # Truncate long responses to keep prompt size reasonable
            full = "".join(assistant_text)
            if len(full) > 500:
                full = full[:500] + "..."
            lines.append(f"Assistant: {full}")
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)

# Greeting words to strip when generating chat titles
_GREETINGS = {"oi", "olá", "ola", "hey", "hi", "hello", "e", "ae", "eae", "bom", "boa",
              "dia", "tarde", "noite", "tudo", "bem", "beleza"}


def _generate_title(prompt: str) -> str:
    """Generate a short contextual title from the first prompt."""
    # Remove line breaks, normalize whitespace
    text = " ".join(prompt.split())
    # Strip common greeting prefixes
    words = text.split()
    # Drop leading greeting words (up to 6)
    start = 0
    for i, w in enumerate(words[:6]):
        clean = w.strip("?,!.").lower()
        if clean in _GREETINGS:
            start = i + 1
        else:
            break
    meaningful = " ".join(words[start:]) if start < len(words) else text
    # Capitalize first letter, truncate to 60 chars
    if not meaningful:
        meaningful = text
    title = meaningful[0].upper() + meaningful[1:] if meaningful else "Chat"
    if len(title) > 60:
        title = title[:57] + "..."
    return title


def _should_create_pr(log_output: str) -> bool:
    """Check if there are commits to push."""
    return bool(log_output.strip())


def register_agent_routes(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
    assert state.session_manager is not None, "session_manager required for agent routes"
    session_manager = state.session_manager

    @app.post("/api/projects/{project_name}/agent", status_code=202, response_model=None)
    async def agent_prompt(
        project_name: str,
        data: dict,
        background_tasks: BackgroundTasks,
    ) -> Response | dict:
        project = state.projects.get(project_name)
        if project is None:
            return Response(status_code=404, content=f"Project {project_name} not found")

        prompt = data.get("prompt", "")
        if not prompt:
            return Response(status_code=400, content="prompt is required")

        session_id = data.get("session_id")
        model = data.get("model", "claude-sonnet-4-6")
        max_cost_usd = data.get("max_cost_usd", 2.0)

        if session_id:
            session = session_manager.get_session(session_id)
            if session is None:
                return Response(status_code=404, content="Session not found")
            if session.status != "active":
                return Response(status_code=410, content="Session closed")
            # Concurrency check before anything else
            if not session_manager.try_acquire_run(session.id):
                return Response(
                    status_code=409,
                    content="A run is already in progress for this session",
                )
            # If worktree is gone (stale session), close it and start fresh
            if not Path(session.worktree_path).exists():
                session_manager.release_run(session.id)
                session_manager.close_session(session_id)
                session = session_manager.create_session(project_name, model, max_cost_usd)
                session_manager.try_acquire_run(session.id)  # always succeeds for fresh session
                is_resume = False
            else:
                # Allow model switch mid-session — clear claude_session_id
                # so executor won't use --resume (API locks model on resume)
                if model != session.model:
                    # Inject conversation history into prompt so new model has context
                    history_context = _build_session_history(session.id, state)
                    if history_context:
                        prompt = history_context + "\n\n---\n\n" + prompt
                    session_manager.update_session(
                        session.id, model=model, claude_session_id="",
                    )
                    session = session_manager.get_session(session_id)
                is_resume = True
        else:
            session = session_manager.create_session(project_name, model, max_cost_usd)
            session_manager.try_acquire_run(session.id)  # always succeeds for fresh session
            is_resume = False
            # Auto-create a work item so no session is orphaned
            if state.task_store:
                title = _generate_title(prompt) or "Chat session"
                state.task_store.create(
                    project=project_name,
                    title=title,
                    description=prompt[:200],
                    source="agent",
                    session_id=session.id,
                )

        run_id = generate_run_id(project_name, "agent")

        async def _run() -> None:
            try:
                async with (
                    state.get_semaphore(config.execution.max_concurrent),
                    state.get_repo_semaphore(project.repo),
                ):
                    result = await state.executor.run_adhoc(
                        project, prompt, session, is_resume=is_resume, run_id=run_id,
                    )
                    # Capture session_id from ClaudeOutput for --resume
                    if result.claude_session_id:
                        session_manager.update_session(
                            session.id, claude_session_id=result.claude_session_id,
                        )
                    elif result.output_file:
                        logger.warning(
                            "No claude_session_id captured for session %s — "
                            "resume will start a fresh conversation",
                            session.id,
                        )
                    # Generate title from first prompt if session has no title yet
                    current = session_manager.get_session(session.id)
                    if current and not current.title and prompt:
                        title = _generate_title(prompt)
                        session_manager.update_session(session.id, title=title)
            finally:
                session_manager.release_run(session.id)

        background_tasks.add_task(_run)
        return {"run_id": run_id, "session_id": session.id, "status": "running"}

    @app.post("/api/sessions/{session_id}/close", response_model=None)
    async def close_session_endpoint(session_id: str) -> Response | dict:
        session = session_manager.get_session(session_id)
        if session is None:
            return Response(status_code=404, content="Session not found")

        pr_url = None
        worktree_path = Path(session.worktree_path)
        project = state.projects.get(session.project)

        # If there are commits, push and create a PR before cleaning up
        if worktree_path.exists() and project:
            try:
                branch = f"agents/session-{session.id}"
                log_output = await state.executor._run_cmd(
                    ["git", "log", f"{project.base_branch}..HEAD", "--oneline"],
                    cwd=str(worktree_path),
                )
                if _should_create_pr(log_output):
                    from agents.pr_body_builder import build_pr_body
                    diff_stat = await state.executor._run_cmd(
                        ["git", "diff", "--stat", f"{project.base_branch}..HEAD"],
                        cwd=str(worktree_path),
                    )
                    body = build_pr_body(
                        project_name=project.name,
                        task_name=f"session-{session.id[:8]}",
                        variables={},
                        diff_stat=diff_stat.strip(),
                        commit_log=log_output.strip(),
                    )
                    await state.executor._run_cmd(
                        ["git", "push", "-u", "origin", branch],
                        cwd=str(worktree_path),
                    )
                    title = session.title or f"Agent session {session.id[:8]}"
                    pr_output = await state.executor._run_cmd(
                        ["gh", "pr", "create", "--title", f"[agents] {title}",
                         "--body", body, "--base", project.base_branch],
                        cwd=str(worktree_path),
                    )
                    pr_url = pr_output.strip()
            except Exception:
                logger.warning("Failed to create PR for session %s", session_id)

        # Clean up
        session_manager.close_session(session_id)
        if worktree_path.exists() and project:
            try:
                await state.executor._run_cmd(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    cwd=project.repo,
                )
            except Exception:
                logger.warning(
                    "Failed to remove worktree %s for session %s",
                    worktree_path, session_id,
                )

        result: dict[str, str | None] = {"status": "closed"}
        if pr_url:
            result["pr_url"] = pr_url
        return result

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str) -> list[dict]:
        """Return all events for all runs in a session, ordered chronologically."""
        runs = state.history.list_runs_by_session(session_id)
        events: list[dict] = []
        for run in runs:
            run_events = state.history.list_events(run.id)
            if run.trigger_type == "agent" and run.task:
                events.append({
                    "type": "user_prompt",
                    "content": run.task,
                    "timestamp": run.started_at.timestamp(),
                })
            events.extend(run_events)
        return events

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str) -> dict:
        """Return events for a single run, with prompt text."""
        run = state.history.get_run(run_id)
        if run is None:
            return {"prompt": "", "events": []}
        events = state.history.list_events(run_id)
        return {
            "prompt": run.task if run.trigger_type == "agent" else "",
            "events": events,
        }
