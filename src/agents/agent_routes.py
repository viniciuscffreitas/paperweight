"""Agent session API route registration."""
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Response

from agents.app_state import AppState
from agents.config import GlobalConfig
from agents.executor_utils import generate_run_id


def register_agent_routes(app: FastAPI, state: AppState, config: GlobalConfig) -> None:
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
            session = state.session_manager.get_session(session_id)
            if session is None:
                return Response(status_code=404, content="Session not found")
            if session.status != "active":
                return Response(status_code=410, content="Session closed")
            is_resume = True
        else:
            session = state.session_manager.create_session(project_name, model, max_cost_usd)
            is_resume = False

        if not state.session_manager.try_acquire_run(session.id):
            return Response(status_code=409, content="A run is already in progress for this session")

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
                    # Capture Claude session_id from raw output for --resume support
                    if result.output_file:
                        import json

                        try:
                            raw = Path(result.output_file).read_text()
                            for line in raw.strip().split("\n"):
                                try:
                                    d = json.loads(line)
                                    if d.get("type") == "result" and d.get("session_id"):
                                        state.session_manager.update_session(
                                            session.id, claude_session_id=d["session_id"],
                                        )
                                        break
                                except json.JSONDecodeError:
                                    continue
                        except FileNotFoundError:
                            pass
            finally:
                state.session_manager.release_run(session.id)

        background_tasks.add_task(_run)
        return {"run_id": run_id, "session_id": session.id, "status": "running"}

    @app.post("/api/sessions/{session_id}/close", response_model=None)
    async def close_session_endpoint(session_id: str) -> Response | dict:
        session = state.session_manager.get_session(session_id)
        if session is None:
            return Response(status_code=404, content="Session not found")
        state.session_manager.close_session(session_id)
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
                pass
        return {"status": "closed"}
