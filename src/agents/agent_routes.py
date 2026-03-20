"""Agent session API route registration."""
import logging
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Response

from agents.app_state import AppState
from agents.config import GlobalConfig
from agents.executor_utils import generate_run_id

logger = logging.getLogger(__name__)


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
                return Response(status_code=409, content="A run is already in progress for this session")
            # If worktree is gone (stale session), close it and start fresh
            if not Path(session.worktree_path).exists():
                session_manager.release_run(session.id)
                session_manager.close_session(session_id)
                session = session_manager.create_session(project_name, model, max_cost_usd)
                session_manager.try_acquire_run(session.id)  # always succeeds for fresh session
                is_resume = False
            else:
                is_resume = True
        else:
            session = session_manager.create_session(project_name, model, max_cost_usd)
            session_manager.try_acquire_run(session.id)  # always succeeds for fresh session
            is_resume = False

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
                    # Capture session_id directly from ClaudeOutput (already parsed by streaming layer)
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
            finally:
                session_manager.release_run(session.id)

        background_tasks.add_task(_run)
        return {"run_id": run_id, "session_id": session.id, "status": "running"}

    @app.post("/api/sessions/{session_id}/close", response_model=None)
    async def close_session_endpoint(session_id: str) -> Response | dict:
        session = session_manager.get_session(session_id)
        if session is None:
            return Response(status_code=404, content="Session not found")
        session_manager.close_session(session_id)
        worktree_path = Path(session.worktree_path)
        if worktree_path.exists():
            try:
                project = state.projects.get(session.project)
                if project:
                    await state.executor._run_cmd(
                        ["git", "worktree", "remove", "--force", str(worktree_path)],
                        cwd=project.repo,
                    )
            except Exception:
                logger.warning(
                    "Failed to remove worktree %s for session %s — manual cleanup may be needed",
                    worktree_path, session_id,
                )
        return {"status": "closed"}
