import os


def test_resolve_env_vars():
    from agents.config import resolve_env_vars

    os.environ["TEST_SECRET"] = "my-secret"
    assert resolve_env_vars("${TEST_SECRET}") == "my-secret"
    assert resolve_env_vars("no-vars-here") == "no-vars-here"
    assert resolve_env_vars("prefix-${TEST_SECRET}-suffix") == "prefix-my-secret-suffix"
    del os.environ["TEST_SECRET"]


def test_resolve_env_vars_missing_returns_empty():
    from agents.config import resolve_env_vars

    assert resolve_env_vars("${NONEXISTENT_VAR}") == ""


def test_load_global_config(tmp_path):
    from agents.config import load_global_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
budget:
  daily_limit_usd: 15.00
  warning_threshold_usd: 10.00
  pause_on_limit: false
notifications:
  slack_webhook_url: https://hooks.slack.com/test
webhooks:
  github_secret: gh-secret
  linear_secret: ln-secret
execution:
  worktree_base: /tmp/test-agents
  default_model: haiku
  default_max_cost_usd: 2.00
  default_autonomy: pr-only
  max_concurrent: 2
  timeout_minutes: 10
  dry_run: true
server:
  host: 127.0.0.1
  port: 9090
""")
    config = load_global_config(config_file)
    assert config.budget.daily_limit_usd == 15.00
    assert config.execution.default_model == "haiku"
    assert config.execution.dry_run is True
    assert config.server.port == 9090


def test_load_project_configs(tmp_path):
    from agents.config import load_project_configs

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "myproject.yaml").write_text("""
name: myproject
repo: /tmp/myrepo
base_branch: develop
tasks:
  lint:
    description: "Run linter"
    schedule: "0 2 * * *"
    model: haiku
    max_cost_usd: 0.50
    prompt: "Run the linter and fix issues"
""")
    projects = load_project_configs(projects_dir)
    assert len(projects) == 1
    assert projects["myproject"].name == "myproject"
    assert projects["myproject"].base_branch == "develop"
    assert "lint" in projects["myproject"].tasks


def test_load_project_configs_skips_example(tmp_path):
    from agents.config import load_project_configs

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    (projects_dir / "example.yaml").write_text("""
name: example
repo: /tmp/example-repo
tasks:
  hello:
    description: "Test"
    schedule: "0 9 * * *"
    prompt: "hello"
""")
    projects = load_project_configs(projects_dir)
    assert len(projects) == 0


def test_render_prompt_template():
    from agents.config import render_prompt

    template = "CI failed on branch {{branch}}. SHA: {{sha}}"
    result = render_prompt(template, {"branch": "main", "sha": "abc123", "extra": "ignored"})
    assert result == "CI failed on branch main. SHA: abc123"


def test_render_prompt_missing_var_left_as_is():
    from agents.config import render_prompt

    template = "Branch: {{branch}}, PR: {{pr_number}}"
    result = render_prompt(template, {"branch": "feat/x"})
    assert result == "Branch: feat/x, PR: {{pr_number}}"
