"""Extended tests for the scheduler module — cron edge cases and job registration."""

import pytest

from agents.models import ProjectConfig, TaskConfig, TriggerConfig

# ---------------------------------------------------------------------------
# parse_cron_to_apscheduler — edge cases
# ---------------------------------------------------------------------------


def test_parse_cron_every_minute():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("* * * * *")
    assert fields["minute"] == "*"
    assert fields["hour"] == "*"
    assert fields["day"] == "*"
    assert fields["month"] == "*"
    assert fields["day_of_week"] == "*"


def test_parse_cron_specific_day_of_week():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 9 * * FRI")
    assert fields["minute"] == "0"
    assert fields["hour"] == "9"
    assert fields["day"] == "*"
    assert fields["month"] == "*"
    assert fields["day_of_week"] == "FRI"


def test_parse_cron_monthly():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 0 1 * *")
    assert fields["minute"] == "0"
    assert fields["hour"] == "0"
    assert fields["day"] == "1"
    assert fields["month"] == "*"
    assert fields["day_of_week"] == "*"


def test_parse_cron_yearly():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 0 1 1 *")
    assert fields["minute"] == "0"
    assert fields["hour"] == "0"
    assert fields["day"] == "1"
    assert fields["month"] == "1"
    assert fields["day_of_week"] == "*"


def test_parse_cron_step_expression():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("*/15 * * * *")
    assert fields["minute"] == "*/15"
    assert fields["hour"] == "*"


def test_parse_cron_range_expression():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 8-18 * * MON-FRI")
    assert fields["hour"] == "8-18"
    assert fields["day_of_week"] == "MON-FRI"


def test_parse_cron_numeric_day_of_week():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 6 * * 1")
    assert fields["day_of_week"] == "1"


# ---------------------------------------------------------------------------
# parse_cron_to_apscheduler — invalid expressions
# ---------------------------------------------------------------------------


def test_parse_cron_too_few_fields():
    from agents.scheduler import parse_cron_to_apscheduler

    with pytest.raises(ValueError, match="Invalid cron expression"):
        parse_cron_to_apscheduler("* * * *")


def test_parse_cron_too_many_fields():
    from agents.scheduler import parse_cron_to_apscheduler

    with pytest.raises(ValueError, match="Invalid cron expression"):
        parse_cron_to_apscheduler("0 3 * * MON extra")


def test_parse_cron_empty_string():
    from agents.scheduler import parse_cron_to_apscheduler

    with pytest.raises(ValueError, match="Invalid cron expression"):
        parse_cron_to_apscheduler("")


def test_parse_cron_only_spaces():
    from agents.scheduler import parse_cron_to_apscheduler

    with pytest.raises(ValueError, match="Invalid cron expression"):
        parse_cron_to_apscheduler("   ")


# ---------------------------------------------------------------------------
# collect_scheduled_tasks — no schedule tasks
# ---------------------------------------------------------------------------


def test_collect_scheduled_tasks_webhook_only():
    from agents.scheduler import collect_scheduled_tasks

    projects = {
        "myapp": ProjectConfig(
            name="myapp",
            repo="/tmp/myapp",
            tasks={
                "on-push": TaskConfig(
                    description="run on push",
                    prompt="fix it",
                    trigger=TriggerConfig(type="github", events=["push"]),
                ),
            },
        ),
    }
    result = collect_scheduled_tasks(projects)
    assert result == []


def test_collect_scheduled_tasks_manual_only():
    from agents.scheduler import collect_scheduled_tasks

    projects = {
        "myapp": ProjectConfig(
            name="myapp",
            repo="/tmp/myapp",
            tasks={
                "manual-run": TaskConfig(
                    description="run manually",
                    prompt="do something",
                ),
            },
        ),
    }
    result = collect_scheduled_tasks(projects)
    assert result == []


def test_collect_scheduled_tasks_mixed_only_schedule_returned():
    from agents.scheduler import collect_scheduled_tasks

    projects = {
        "myapp": ProjectConfig(
            name="myapp",
            repo="/tmp/myapp",
            tasks={
                "nightly": TaskConfig(description="t", prompt="p", schedule="0 2 * * *"),
                "on-pr": TaskConfig(
                    description="t",
                    prompt="p",
                    trigger=TriggerConfig(type="github", events=["pull_request"]),
                ),
                "manual": TaskConfig(description="t", prompt="p"),
            },
        ),
    }
    result = collect_scheduled_tasks(projects)
    assert len(result) == 1
    assert result[0] == ("myapp", "nightly", "0 2 * * *")


# ---------------------------------------------------------------------------
# register_jobs
# ---------------------------------------------------------------------------


def _make_scheduler():
    """Return an AsyncIOScheduler without starting it (no event loop needed)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    return AsyncIOScheduler()


async def _dummy_callback(**kwargs):
    pass


def test_register_jobs_adds_new_job():
    from agents.scheduler import register_jobs

    sched = _make_scheduler()
    projects = {
        "alpha": ProjectConfig(
            name="alpha",
            repo="/tmp/alpha",
            tasks={
                "weekly": TaskConfig(description="t", prompt="p", schedule="0 3 * * MON"),
            },
        ),
    }
    register_jobs(sched, projects, _dummy_callback)
    job_ids = {job.id for job in sched.get_jobs()}
    assert "alpha:weekly" in job_ids


def test_register_jobs_no_schedule_tasks_registers_nothing():
    from agents.scheduler import register_jobs

    sched = _make_scheduler()
    projects = {
        "beta": ProjectConfig(
            name="beta",
            repo="/tmp/beta",
            tasks={
                "on-push": TaskConfig(
                    description="t",
                    prompt="p",
                    trigger=TriggerConfig(type="github", events=["push"]),
                ),
            },
        ),
    }
    register_jobs(sched, projects, _dummy_callback)
    assert sched.get_jobs() == []


def test_register_jobs_multiple_projects():
    from agents.scheduler import register_jobs

    sched = _make_scheduler()
    projects = {
        "proj-a": ProjectConfig(
            name="proj-a",
            repo="/tmp/proj-a",
            tasks={
                "task-1": TaskConfig(description="t", prompt="p", schedule="0 1 * * *"),
                "task-2": TaskConfig(description="t", prompt="p", schedule="0 2 * * *"),
            },
        ),
        "proj-b": ProjectConfig(
            name="proj-b",
            repo="/tmp/proj-b",
            tasks={
                "task-x": TaskConfig(description="t", prompt="p", schedule="30 4 * * FRI"),
            },
        ),
    }
    register_jobs(sched, projects, _dummy_callback)
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"proj-a:task-1", "proj-a:task-2", "proj-b:task-x"}


def test_register_jobs_removes_stale_job():
    from agents.scheduler import register_jobs

    sched = _make_scheduler()

    # Register an initial set
    projects_v1 = {
        "proj": ProjectConfig(
            name="proj",
            repo="/tmp/proj",
            tasks={
                "old-task": TaskConfig(description="t", prompt="p", schedule="0 0 * * *"),
                "keep-task": TaskConfig(description="t", prompt="p", schedule="0 1 * * *"),
            },
        ),
    }
    register_jobs(sched, projects_v1, _dummy_callback)
    assert {j.id for j in sched.get_jobs()} == {"proj:old-task", "proj:keep-task"}

    # Re-register without old-task — it should be removed
    projects_v2 = {
        "proj": ProjectConfig(
            name="proj",
            repo="/tmp/proj",
            tasks={
                "keep-task": TaskConfig(description="t", prompt="p", schedule="0 1 * * *"),
            },
        ),
    }
    register_jobs(sched, projects_v2, _dummy_callback)
    job_ids = {j.id for j in sched.get_jobs()}
    assert "proj:old-task" not in job_ids
    assert "proj:keep-task" in job_ids


def test_register_jobs_reschedules_existing_job():
    from agents.scheduler import register_jobs

    sched = _make_scheduler()
    projects_v1 = {
        "proj": ProjectConfig(
            name="proj",
            repo="/tmp/proj",
            tasks={
                "daily": TaskConfig(description="t", prompt="p", schedule="0 6 * * *"),
            },
        ),
    }
    register_jobs(sched, projects_v1, _dummy_callback)

    # Change the schedule
    projects_v2 = {
        "proj": ProjectConfig(
            name="proj",
            repo="/tmp/proj",
            tasks={
                "daily": TaskConfig(description="t", prompt="p", schedule="0 9 * * *"),
            },
        ),
    }
    register_jobs(sched, projects_v2, _dummy_callback)

    # Job still exists, not duplicated
    jobs = [j for j in sched.get_jobs() if j.id == "proj:daily"]
    assert len(jobs) == 1
