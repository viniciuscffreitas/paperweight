"""Project setup wizard — create and configure projects via dashboard."""
from nicegui import ui


def setup_wizard_page(app, state) -> None:
    @ui.page("/dashboard/project/new")
    async def new_project_page() -> None:
        ui.label("New Project").classes("text-2xl font-bold text-white mb-4")
        stepper = ui.stepper().classes("w-full")

        with stepper:
            # Step 1: Basics
            with ui.step("Basics"):
                name_input = ui.input("Project Name", placeholder="MomEase").classes("w-full")
                repo_input = ui.input("Repository Path", placeholder="/Users/you/repos/momease").classes("w-full")
                branch_input = ui.input("Default Branch", value="main").classes("w-full")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=stepper.next).props("color=blue")

            # Step 2: Discover Sources
            with ui.step("Discover Sources"):
                discovery_container = ui.column().classes("w-full")
                discovered_sources = []

                async def run_discovery():
                    discovery_container.clear()
                    project_name = name_input.value
                    if not project_name:
                        with discovery_container:
                            ui.label("Enter a project name first").classes("text-red-400")
                        return
                    with discovery_container:
                        ui.label("Searching...").classes("text-gray-400 italic")

                    results = await _discover_sources(project_name, state)
                    discovered_sources.clear()
                    discovered_sources.extend(results)

                    discovery_container.clear()
                    with discovery_container:
                        if not results:
                            ui.label("No sources found. You can add them manually later.").classes("text-gray-400")
                        for r in results:
                            cb = ui.checkbox(
                                f"{r['source_type'].upper()}: {r['source_name']}",
                                value=r.get("confidence", "low") != "low",
                            )
                            r["checkbox"] = cb

                ui.button("Search", icon="search", on_click=run_discovery).props("color=blue")
                with ui.stepper_navigation():
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Next", on_click=stepper.next).props("color=blue")

            # Step 3: Notifications
            with ui.step("Notifications"):
                notify_channel = ui.select(options=["slack", "discord", "both"], value="slack", label="Notification Channel").classes("w-full")
                digest_time = ui.input("Digest Time", value="09:00").classes("w-full")
                alerts_enabled = ui.checkbox("Enable urgent alerts", value=True)

                with ui.stepper_navigation():
                    ui.button("Back", on_click=stepper.previous).props("flat")

                    async def create_project():
                        project_id = name_input.value.lower().replace(" ", "-")
                        state.project_store.create_project(
                            id=project_id, name=name_input.value,
                            repo_path=repo_input.value, default_branch=branch_input.value,
                        )
                        for r in discovered_sources:
                            if hasattr(r.get("checkbox"), "value") and r["checkbox"].value:
                                state.project_store.create_source(
                                    project_id=project_id, source_type=r["source_type"],
                                    source_id=r["source_id"], source_name=r["source_name"],
                                )
                        channels = ["slack", "discord"] if notify_channel.value == "both" else [notify_channel.value]
                        for ch in channels:
                            state.project_store.create_notification_rule(
                                project_id=project_id, rule_type="digest", channel=ch,
                                channel_target="dm", config={"schedule": digest_time.value},
                            )
                            if alerts_enabled.value:
                                state.project_store.create_notification_rule(
                                    project_id=project_id, rule_type="alert", channel=ch,
                                    channel_target="dm",
                                    config={"events": ["urgent_issue", "ci_failure", "mention", "run_failure"]},
                                )
                        ui.notify("Project created!", type="positive")
                        ui.navigate.to(f"/dashboard/project/{project_id}")

                    ui.button("Create Project", on_click=create_project).props("color=green")


async def _discover_sources(name: str, state) -> list[dict]:
    """Run auto-discovery across all configured integrations."""
    results = []
    query = name.lower().replace(" ", "").replace("-", "")

    # Linear discovery
    if hasattr(state, "linear_client") and state.linear_client:
        try:
            teams = await state.linear_client.fetch_teams()
            for team_name, team_id in teams.items():
                if query in team_name.replace("-", "").replace(" ", ""):
                    results.append({
                        "source_type": "linear", "source_id": team_id,
                        "source_name": f"Team: {team_name}",
                        "confidence": "high" if query == team_name.replace("-", "").replace(" ", "") else "medium",
                    })
        except Exception:
            pass

    # GitHub discovery
    if hasattr(state, "github_client") and state.github_client:
        try:
            repos = await state.github_client.search_repos("", name)
            for repo in repos[:5]:
                results.append({
                    "source_type": "github", "source_id": repo.get("full_name", ""),
                    "source_name": f"Repo: {repo.get('name', '')}",
                    "confidence": "high" if query in repo.get("full_name", "").lower().replace("-", "") else "medium",
                })
        except Exception:
            pass

    # Slack discovery
    if hasattr(state, "slack_bot_client") and state.slack_bot_client:
        try:
            channels = await state.slack_bot_client.search_channels_by_name(name)
            for ch in channels[:5]:
                results.append({
                    "source_type": "slack", "source_id": ch["id"],
                    "source_name": f"#{ch['name']}",
                    "confidence": "high" if query in ch["name"].replace("-", "") else "medium",
                })
        except Exception:
            pass

    return results
