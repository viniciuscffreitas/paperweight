def test_parse_cron_fields():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("0 3 * * MON")
    assert fields["minute"] == "0"
    assert fields["hour"] == "3"
    assert fields["day"] == "*"
    assert fields["month"] == "*"
    assert fields["day_of_week"] == "MON"


def test_parse_cron_every_hour():
    from agents.scheduler import parse_cron_to_apscheduler

    fields = parse_cron_to_apscheduler("30 * * * *")
    assert fields["minute"] == "30"
    assert fields["hour"] == "*"


def test_build_job_id():
    from agents.scheduler import build_job_id

    assert build_job_id("sekit", "dep-update") == "sekit:dep-update"


def test_collect_scheduled_tasks():
    from agents.models import ProjectConfig, TaskConfig, TriggerConfig
    from agents.scheduler import collect_scheduled_tasks

    projects = {
        "sekit": ProjectConfig(
            name="sekit",
            repo="/tmp/sekit",
            tasks={
                "dep-update": TaskConfig(description="t", prompt="p", schedule="0 3 * * MON"),
                "ci-fix": TaskConfig(
                    description="t",
                    prompt="p",
                    trigger=TriggerConfig(type="github", events=["push"]),
                ),
            },
        ),
    }
    scheduled = collect_scheduled_tasks(projects)
    assert len(scheduled) == 1
    assert scheduled[0] == ("sekit", "dep-update", "0 3 * * MON")
