import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agents.models import ProjectConfig

logger = logging.getLogger(__name__)


def parse_cron_to_apscheduler(cron_expr: str) -> dict[str, str]:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        msg = f"Invalid cron expression: {cron_expr}"
        raise ValueError(msg)
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def build_job_id(project_name: str, task_name: str) -> str:
    return f"{project_name}:{task_name}"


def collect_scheduled_tasks(
    projects: dict[str, ProjectConfig],
) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    for project_name, project in projects.items():
        for task_name, task in project.tasks.items():
            if task.schedule:
                result.append((project_name, task_name, task.schedule))
    return result


def create_scheduler(db_path: str) -> AsyncIOScheduler:
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")}
    return AsyncIOScheduler(jobstores=jobstores)


def register_jobs(
    scheduler: AsyncIOScheduler, projects: dict[str, ProjectConfig], run_task_callback: object
) -> None:
    scheduled = collect_scheduled_tasks(projects)
    existing_jobs = {job.id for job in scheduler.get_jobs()}
    for project_name, task_name, cron_expr in scheduled:
        job_id = build_job_id(project_name, task_name)
        cron_fields = parse_cron_to_apscheduler(cron_expr)
        if job_id in existing_jobs:
            scheduler.reschedule_job(job_id, trigger="cron", **cron_fields)
            existing_jobs.discard(job_id)
        else:
            scheduler.add_job(
                run_task_callback,
                trigger="cron",
                id=job_id,
                kwargs={"project_name": project_name, "task_name": task_name},
                **cron_fields,
                replace_existing=True,
            )
    for old_id in existing_jobs:
        scheduler.remove_job(old_id)
        logger.info("Removed stale job: %s", old_id)
