# Settings Page — Full App Configuration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the Settings page from API-key-only to a comprehensive configuration hub with Account, Execution, Budget, and Integrations sections.

**Architecture:** Settings page uses a sectioned layout. Account settings (API key, password) are per-user and stored in auth.db with immediate effect. App-level settings (execution, budget) are read from / written to `config.yaml` and require a process restart. Integration status is shown read-only (managed via env vars). Admin-only sections are hidden from non-admin users.

**Tech Stack:** FastAPI, Jinja2, HTMX, SQLite (auth.db), PyYAML (config.yaml read/write)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/agents/auth.py` | Add `change_password()` method to AuthDB |
| `src/agents/auth_routes.py` | Expand GET/POST settings routes, add password change and config save endpoints |
| `src/agents/config_writer.py` | **New** — read raw config.yaml + write back with value updates (preserves env var references) |
| `src/agents/templates/settings.html` | Redesigned template with all sections |
| `tests/test_settings_routes.py` | Expand with tests for password change, config display, config save |
| `tests/test_config_writer.py` | **New** — tests for config read/write utilities |

## Design Decisions

1. **Config editing strategy**: Read raw YAML to detect `${ENV_VAR}` patterns. Fields using env vars are shown as read-only ("Configured via environment variable"). Plain values are editable. Write-back preserves env var references by only updating fields the user changed.

2. **Restart semantics**: App-level config changes (budget, execution) write to `config.yaml` but require restart. A banner says "Changes saved. Restart required to apply." Account changes (password, API key) are immediate.

3. **Admin gating**: Execution, Budget, and Integrations sections only render for `user.is_admin == True`. Non-admin users see only the Account section.

4. **Form separation**: Each section submits to its own POST endpoint to avoid accidentally overwriting unrelated settings. Account: `POST /settings/account`, Password: `POST /settings/password`, Config: `POST /settings/config`.

---

### Task 1: Password Change Backend

**Files:**
- Modify: `src/agents/auth.py` — add `change_password()` method
- Test: `tests/test_auth.py` — add password change tests

- [ ] **Step 1: Write failing tests for password change**

Add to `tests/test_auth.py`:

```python
def test_change_password_success(db: AuthDB) -> None:
    db.create_user("alice", "old-password")
    result = db.change_password("alice", "old-password", "new-password")
    assert result is True
    assert db.authenticate("alice", "new-password") is not None
    assert db.authenticate("alice", "old-password") is None


def test_change_password_wrong_current(db: AuthDB) -> None:
    db.create_user("bob", "correct")
    result = db.change_password("bob", "wrong", "new-password")
    assert result is False
    # Original password still works
    assert db.authenticate("bob", "correct") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth.py::test_change_password_success tests/test_auth.py::test_change_password_wrong_current -v`
Expected: FAIL — `AuthDB` has no `change_password` method

- [ ] **Step 3: Implement `change_password` in AuthDB**

Add to `src/agents/auth.py` in the `AuthDB` class, after `update_api_key`:

```python
def change_password(self, username: str, current_password: str, new_password: str) -> bool:
    """Change password if current_password is correct. Returns True on success."""
    user = self.authenticate(username, current_password)
    if user is None:
        return False
    salt = secrets.token_hex(32)
    hashed = hash_password(new_password, salt)
    with self._conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (hashed, salt, user.id),
        )
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_auth.py::test_change_password_success tests/test_auth.py::test_change_password_wrong_current -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/auth.py tests/test_auth.py
git commit -m "feat: add change_password to AuthDB"
```

---

### Task 2: Config Reader/Writer Utility

**Files:**
- Create: `src/agents/config_writer.py`
- Test create: `tests/test_config_writer.py`

- [ ] **Step 1: Write failing tests for config reader/writer**

Create `tests/test_config_writer.py`:

```python
"""Tests for config_writer — read/write config.yaml preserving env var references."""
from pathlib import Path

from agents.config_writer import read_raw_config, write_config_values, is_env_var


def test_is_env_var_true():
    assert is_env_var("${LINEAR_API_KEY}") is True


def test_is_env_var_false():
    assert is_env_var("sonnet") is False
    assert is_env_var("") is False
    assert is_env_var("100.0") is False


def test_read_raw_config(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("budget:\n  daily_limit_usd: 50.00\nexecution:\n  default_model: sonnet\n")
    raw = read_raw_config(cfg)
    assert raw["budget"]["daily_limit_usd"] == 50.0
    assert raw["execution"]["default_model"] == "sonnet"


def test_write_config_values_updates_plain(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("budget:\n  daily_limit_usd: 50.00\n  pause_on_limit: true\n")
    write_config_values(cfg, {"budget": {"daily_limit_usd": 100.0}})
    raw = read_raw_config(cfg)
    assert raw["budget"]["daily_limit_usd"] == 100.0
    assert raw["budget"]["pause_on_limit"] is True  # unchanged


def test_write_config_values_preserves_env_vars(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("integrations:\n  linear_api_key: ${LINEAR_API_KEY}\n  github_token: my-token\n")
    write_config_values(cfg, {"integrations": {"github_token": "new-token"}})
    text = cfg.read_text()
    assert "${LINEAR_API_KEY}" in text  # env var preserved
    raw = read_raw_config(cfg)
    assert raw["integrations"]["github_token"] == "new-token"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_writer.py -v`
Expected: FAIL — module `agents.config_writer` not found

- [ ] **Step 3: Implement config_writer.py**

Create `src/agents/config_writer.py`:

```python
"""Read and write config.yaml, preserving ${ENV_VAR} references."""
import re
from pathlib import Path

import yaml


def is_env_var(value: str) -> bool:
    """Check if a string value is an env var reference like ${FOO}."""
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"\$\{\w+\}", value.strip()))


def read_raw_config(path: Path) -> dict:
    """Read config.yaml without resolving env vars."""
    return yaml.safe_load(path.read_text()) or {}


def _deep_merge(base: dict, updates: dict) -> dict:
    """Merge updates into base, only overwriting leaf values."""
    merged = dict(base)
    for key, value in updates.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _strip_env_vars(current: dict, updates: dict) -> dict:
    """Remove update keys where the current value is an env var reference."""
    clean: dict = {}
    for key, value in updates.items():
        cur = current.get(key)
        if isinstance(value, dict) and isinstance(cur, dict):
            nested = _strip_env_vars(cur, value)
            if nested:
                clean[key] = nested
        elif not is_env_var(str(cur or "")):
            clean[key] = value
    return clean


def write_config_values(path: Path, updates: dict) -> None:
    """Update specific values in config.yaml, preserving structure and env vars."""
    current = read_raw_config(path)
    safe_updates = _strip_env_vars(current, updates)
    merged = _deep_merge(current, safe_updates)
    path.write_text(yaml.dump(merged, default_flow_style=False, sort_keys=False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_writer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/config_writer.py tests/test_config_writer.py
git commit -m "feat: config_writer — read/write config.yaml preserving env vars"
```

---

### Task 3: Settings Routes Expansion

**Files:**
- Modify: `src/agents/auth_routes.py` — refactor GET /settings, add POST endpoints
- Modify: `tests/test_settings_routes.py` — add tests for new endpoints

- [ ] **Step 1: Write failing tests for password change route**

Add to `tests/test_settings_routes.py`:

```python
def test_post_password_change_success(client: TestClient, auth_db: AuthDB) -> None:
    resp = client.post(
        "/settings/password",
        data={"current_password": "password123", "new_password": "newpass456"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "saved=password" in resp.headers["location"]
    assert auth_db.authenticate("testuser", "newpass456") is not None


def test_post_password_change_wrong_current(client: TestClient) -> None:
    resp = client.post(
        "/settings/password",
        data={"current_password": "wrong", "new_password": "newpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=password" in resp.headers["location"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settings_routes.py::test_post_password_change_success tests/test_settings_routes.py::test_post_password_change_wrong_current -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Write failing tests for config display and save**

Add to `tests/test_settings_routes.py`:

```python
def test_get_settings_shows_execution_config_for_admin(admin_client: TestClient) -> None:
    resp = admin_client.get("/settings")
    assert resp.status_code == 200
    assert "Execution" in resp.text
    assert "Budget" in resp.text


def test_get_settings_hides_admin_sections_for_regular_user(client: TestClient) -> None:
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Account" in resp.text
    # Non-admin should not see admin sections
    assert "Execution" not in resp.text


def test_post_config_saves_values(admin_client: TestClient, config_path: Path) -> None:
    resp = admin_client.post(
        "/settings/config",
        data={"budget.daily_limit_usd": "200.00", "execution.default_model": "opus"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    from agents.config_writer import read_raw_config
    raw = read_raw_config(config_path)
    assert raw["budget"]["daily_limit_usd"] == 200.0
    assert raw["execution"]["default_model"] == "opus"


def test_post_config_rejected_for_non_admin(client: TestClient) -> None:
    resp = client.post(
        "/settings/config",
        data={"budget.daily_limit_usd": "999"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/settings" in resp.headers["location"]
```

These tests require new fixtures: `admin_client` (user with `is_admin=True`) and `config_path` (temp config.yaml). Add to conftest or top of file:

```python
@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "budget:\n  daily_limit_usd: 100.0\n  warning_threshold_usd: 80.0\n  pause_on_limit: false\n"
        "execution:\n  default_model: sonnet\n  max_concurrent: 3\n  timeout_minutes: 30\n"
        "  default_max_cost_usd: 5.0\n  default_autonomy: pr-only\n  dry_run: false\n"
    )
    return cfg


@pytest.fixture
def admin_client(auth_db: AuthDB, config_path: Path) -> TestClient:
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.config_path = config_path

    @app.middleware("http")
    async def inject_projects(request: Request, call_next):
        request.state.projects = []
        return await call_next(request)

    register_auth_routes(app, auth_db, templates)

    user = auth_db.create_user("admin", "adminpass", is_admin=True)
    token = auth_db.create_session(user.id)

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        if request.cookies.get("pw_session") == token:
            request.state.user = auth_db.get_session_user(token)
        return await call_next(request)

    return TestClient(app, cookies={"pw_session": token})
```

- [ ] **Step 4: Run tests to verify all new tests fail**

Run: `uv run pytest tests/test_settings_routes.py -v -k "admin or password or config"`
Expected: FAIL

- [ ] **Step 5: Implement routes**

In `src/agents/auth_routes.py`, update `register_auth_routes` signature to accept optional `config_path`:

```python
def register_auth_routes(
    app: FastAPI, auth_db: AuthDB, templates: Jinja2Templates
) -> None:
```

Update `GET /settings` to load config for admin users:

```python
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    projects = getattr(request.state, "projects", [])
    masked_key = _mask_api_key(user.api_key)

    config_data = {}
    integrations_status = {}
    config_path = getattr(request.app.state, "config_path", None)
    if user.is_admin and config_path:
        from agents.config_writer import read_raw_config, is_env_var
        raw = read_raw_config(config_path)
        config_data = raw
        # Build integration status
        from agents.config import resolve_env_vars
        integ = raw.get("integrations", {})
        for key, val in integ.items():
            resolved = resolve_env_vars(str(val)) if is_env_var(str(val)) else str(val)
            integrations_status[key] = bool(resolved)

    saved = request.query_params.get("saved", "")
    error = request.query_params.get("error", "")

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "masked_key": masked_key,
            "projects": projects,
            "config": config_data,
            "integrations_status": integrations_status,
            "saved": saved,
            "error": error,
        },
    )
```

Add `POST /settings/account` (rename existing API key save):

```python
@app.post("/settings/account", response_class=HTMLResponse)
async def settings_save_account(request: Request) -> Response:
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    api_key = str(form.get("api_key", "")).strip()
    auth_db.update_api_key(user.id, api_key)
    return RedirectResponse("/settings?saved=account", status_code=303)
```

Add `POST /settings/password`:

```python
@app.post("/settings/password", response_class=HTMLResponse)
async def settings_change_password(request: Request) -> Response:
    user = getattr(request.state, "user", None)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    current = str(form.get("current_password", ""))
    new = str(form.get("new_password", ""))
    if not current or not new:
        return RedirectResponse("/settings?error=password", status_code=303)
    ok = auth_db.change_password(user.username, current, new)
    if not ok:
        return RedirectResponse("/settings?error=password", status_code=303)
    return RedirectResponse("/settings?saved=password", status_code=303)
```

Add `POST /settings/config` (admin-only):

```python
@app.post("/settings/config", response_class=HTMLResponse)
async def settings_save_config(request: Request) -> Response:
    user = getattr(request.state, "user", None)
    if user is None or not user.is_admin:
        return RedirectResponse("/settings", status_code=303)
    config_path = getattr(request.app.state, "config_path", None)
    if not config_path:
        return RedirectResponse("/settings?error=config", status_code=303)
    form = await request.form()
    updates: dict = {}
    for key, value in form.items():
        parts = key.split(".")
        if len(parts) == 2:
            section, field = parts
            updates.setdefault(section, {})[field] = _coerce_value(value)
    if updates:
        from agents.config_writer import write_config_values
        write_config_values(config_path, updates)
    return RedirectResponse("/settings?saved=config", status_code=303)


def _coerce_value(val: str):
    """Coerce form string to appropriate Python type."""
    if val == "":
        return ""
    if val.lower() in ("true", "on"):
        return True
    if val.lower() in ("false", "off"):
        return False
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val
```

- [ ] **Step 6: Store config_path in app.state during startup**

In `src/agents/main.py`, after `config = load_global_config(config_path)`, add:

```python
app.state.config_path = config_path
```

This makes the config file path available to settings routes.

- [ ] **Step 7: Update existing POST /settings to POST /settings/account**

Remove the old `POST /settings` route (replaced by `/settings/account`). Keep `GET /settings`.
Also update existing tests in `tests/test_settings_routes.py` that POST to `/settings` to use `/settings/account` instead (`test_post_settings_updates_api_key`, `test_post_settings_clears_api_key`).

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_settings_routes.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/agents/auth_routes.py src/agents/main.py tests/test_settings_routes.py
git commit -m "feat: settings routes — password change, config display/save"
```

---

### Task 4: Settings Template Redesign

**Files:**
- Modify: `src/agents/templates/settings.html` — full sectioned layout

- [ ] **Step 1: Redesign the template**

The template should have these sections:

**1. Flash messages** — based on `saved` and `error` query params

**2. Account section** (all users):
- Username (read-only)
- API key (masked + update form → POST /settings/account)
- Password change (current + new → POST /settings/password)

**3. Execution section** (admin only):
- Default model (select: sonnet/opus/haiku)
- Max concurrent (number input)
- Timeout minutes (number input)
- Default max cost USD (number input)
- Default autonomy (select: pr-only/full/yolo)
- Dry run (checkbox)

**4. Budget section** (admin only):
- Daily limit USD (number input)
- Warning threshold USD (number input)
- Pause on limit (checkbox)

**5. Integrations section** (admin only, read-only):
- Each integration shows a status dot (green = connected, gray = not configured)
- Linear, GitHub, Slack Bot, Discord, Slack Webhook
- Hint text: "Managed via environment variables"

Sections 3, 4, 5 are wrapped in `{% if user.is_admin %}`.
Sections 3 and 4 share a single form → POST /settings/config.
Section 5 has no form (read-only).

Use design system tokens from `macros.html`. Match existing auth page aesthetics.

Full template code: see implementation (too large for plan, but structure is defined above).

- [ ] **Step 2: Verify template renders**

Run: `uv run pytest tests/test_settings_routes.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agents/templates/settings.html tests/test_settings_routes.py
git commit -m "feat: settings template — account, execution, budget, integrations"
```

---

### Task 5: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -q --tb=short
```

Expected: all tests pass, no regressions

- [ ] **Step 2: Run linter**

```bash
uv run ruff check src/ tests/ --fix
```

Expected: clean

- [ ] **Step 3: Final commit if any fixes**

```bash
git add -A && git commit -m "fix: lint and test cleanup for settings"
```

- [ ] **Step 4: Deploy**

```bash
git push origin main
ssh vinicius@vinicius.xyz 'cd ~/paperweight && git pull && ~/.local/bin/uv sync && pm2 reload paperweight'
```
