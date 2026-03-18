# Light Theme Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar light theme warm (creme/areia) com toggle no header, persistido em cookie HTTP-only.

**Architecture:** CSS custom properties em `[data-theme="light"]` sobrescrevem os tokens de `:root`. O Jinja2 injeta `data-theme` no `<html>` a partir do cookie `theme`. Um endpoint `POST /set-theme` seta o cookie; JS troca o `data-theme` sem reload com rollback em caso de falha.

**Tech Stack:** FastAPI, Jinja2, CSS custom properties, HTMX, pytest + FastAPI TestClient

**Spec:** `docs/superpowers/specs/2026-03-18-light-theme-design.md`

---

## Chunk 1: CSS — Overlay tokens + bloco light theme

**Files:**
- Modify: `src/agents/static/dashboard.css`
- Test: `tests/test_dashboard_html.py` (append)

---

### Task 1: Tokens de overlay no `:root`

**Files:**
- Modify: `src/agents/static/dashboard.css`
- Test: `tests/test_dashboard_html.py`

- [ ] **Step 1: Escrever o teste que FALHA**

Em `tests/test_dashboard_html.py`, adicionar ao final do arquivo:

```python
# ---------------------------------------------------------------------------
# Light Theme — CSS
# ---------------------------------------------------------------------------

def _read_css() -> str:
    import os
    css_path = os.path.join(
        os.path.dirname(__file__), "../src/agents/static/dashboard.css"
    )
    with open(css_path) as f:
        return f.read()


def test_css_overlay_tokens_in_root():
    """dashboard.css :root must define --overlay-backdrop and --overlay-shadow tokens."""
    css = _read_css()
    assert "--overlay-backdrop:" in css
    assert "--overlay-shadow:" in css


def test_css_light_theme_block_exists():
    """dashboard.css must contain a [data-theme="light"] block."""
    css = _read_css()
    assert '[data-theme="light"]' in css


def test_css_light_theme_overrides_all_bg_tokens():
    """[data-theme="light"] block must override all --bg-* tokens."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    assert light_block_start != -1
    light_block = css[light_block_start:]
    for token in [
        "--bg-chrome", "--bg-content", "--bg-elevated", "--bg-overlay",
        "--bg-task-success", "--bg-task-error", "--bg-task-hover",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"


def test_css_light_theme_overrides_all_text_tokens():
    """[data-theme="light"] block must override all --text-* tokens."""
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    light_block = css[light_block_start:]
    for token in [
        "--text-primary", "--text-secondary", "--text-muted",
        "--text-disabled", "--text-placeholder",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"


def test_css_light_theme_overrides_border_and_accent_tokens():
    css = _read_css()
    light_block_start = css.find('[data-theme="light"]')
    light_block = css[light_block_start:]
    for token in [
        "--border-subtle", "--border-default", "--border-strong",
        "--accent", "--accent-bg", "--accent-hover",
        "--overlay-backdrop", "--overlay-shadow",
    ]:
        assert token in light_block, f"Missing {token} in light theme block"
```

- [ ] **Step 2: Rodar e confirmar FALHA**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_css_overlay_tokens_in_root tests/test_dashboard_html.py::test_css_light_theme_block_exists -v
```
Esperado: FAIL — tokens não existem ainda.

- [ ] **Step 3: Implementar — adicionar tokens ao `:root` e bloco light**

Em `src/agents/static/dashboard.css`, adicionar `--overlay-backdrop` e `--overlay-shadow` ao bloco `:root` existente (após `--status-neutral`):

```css
  /* overlay rgba — tokenized for theme support */
  --overlay-backdrop: rgba(0,0,0,0.45);
  --overlay-shadow:   rgba(0,0,0,0.65);
```

Após o bloco `:root { ... }` (após a linha do comentário sobre rgba), adicionar:

```css
[data-theme="light"] {
  /* backgrounds */
  --bg-chrome:    #f5f0e8;
  --bg-content:   #fdfaf4;
  --bg-elevated:  #ede8df;
  --bg-overlay:   #e8e2d8;

  /* borders */
  --border-subtle:  #ddd8ce;
  --border-default: #c8c2b8;
  --border-strong:  #a89e92;

  /* text */
  --text-primary:     #1a1612;
  --text-secondary:   #5c5248;
  --text-muted:       #8a8078;
  --text-disabled:    #b0a89e;
  --text-placeholder: #c0b8ae;

  /* accent */
  --accent:       #2563eb;
  --accent-bg:    #dbeafe;
  --accent-hover: #1e40af;

  /* task row semantic backgrounds */
  --bg-task-success: #dcfce7;
  --bg-task-error:   #fee2e2;
  --bg-task-hover:   #ede8df;

  /* overlay rgba — warm brown for light theme */
  --overlay-backdrop: rgba(80,60,40,0.35);
  --overlay-shadow:   rgba(80,60,40,0.50);
}
```

- [ ] **Step 4: Rodar e confirmar PASS**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_css_overlay_tokens_in_root tests/test_dashboard_html.py::test_css_light_theme_block_exists tests/test_dashboard_html.py::test_css_light_theme_overrides_all_bg_tokens tests/test_dashboard_html.py::test_css_light_theme_overrides_all_text_tokens tests/test_dashboard_html.py::test_css_light_theme_overrides_border_and_accent_tokens -v
```
Esperado: todos PASS.

- [ ] **Step 5: Suite completa — sem regressões**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py -v
```
Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agents/static/dashboard.css tests/test_dashboard_html.py
git commit -m "feat(theme): CSS tokens de overlay + bloco [data-theme=\"light\"] warm"
```

---

## Chunk 2: Endpoint POST /set-theme

**Files:**
- Modify: `src/agents/dashboard_html.py`
- Test: `tests/test_dashboard_html.py` (append)

---

### Task 2: Endpoint `POST /set-theme`

- [ ] **Step 1: Escrever os testes que FALHAM**

Adicionar ao final de `tests/test_dashboard_html.py`:

```python
# ---------------------------------------------------------------------------
# Light Theme — Endpoint POST /set-theme
# ---------------------------------------------------------------------------


def test_set_theme_light_sets_cookie(app_with_dashboard):
    """POST /set-theme com theme=light seta o cookie theme=light."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "light"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "theme" in resp.cookies
    assert resp.cookies["theme"] == "light"


def test_set_theme_dark_sets_cookie(app_with_dashboard):
    """POST /set-theme com theme=dark seta o cookie theme=dark."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "dark"})
    assert resp.status_code == 200
    assert resp.cookies["theme"] == "dark"


def test_set_theme_invalid_returns_422(app_with_dashboard):
    """POST /set-theme com valor inválido retorna 422."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "hacker"})
    assert resp.status_code == 422


def test_set_theme_missing_body_returns_422(app_with_dashboard):
    """POST /set-theme sem body retorna 422."""
    resp = app_with_dashboard.post("/set-theme", data={})
    assert resp.status_code == 422


def test_set_theme_cookie_attributes(app_with_dashboard):
    """Cookie deve ter httponly, samesite=lax e max-age corretos."""
    resp = app_with_dashboard.post("/set-theme", data={"theme": "light"})
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=31536000" in set_cookie
```

- [ ] **Step 2: Rodar e confirmar FALHA**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_set_theme_light_sets_cookie tests/test_dashboard_html.py::test_set_theme_invalid_returns_422 -v
```
Esperado: FAIL — endpoint não existe (404).

- [ ] **Step 3: Implementar o endpoint**

Em `src/agents/dashboard_html.py`, adicionar `Form, HTTPException` ao import:

```python
from fastapi import Form, HTTPException, Request
```
(Linha 9 atual: `from fastapi import Request` — substituir por linha acima.)

Dentro de `setup_dashboard()`, após o último endpoint existente, adicionar:

```python
    @app.post("/set-theme")
    async def set_theme(response: Response, theme: str = Form(...)) -> dict:
        if theme not in ("light", "dark"):
            raise HTTPException(status_code=422, detail="Invalid theme value")
        response.set_cookie(
            "theme", theme,
            max_age=31_536_000, path="/",
            httponly=True, samesite="lax",
        )
        return {"ok": True}
```

- [ ] **Step 4: Rodar e confirmar PASS**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_set_theme_light_sets_cookie tests/test_dashboard_html.py::test_set_theme_dark_sets_cookie tests/test_dashboard_html.py::test_set_theme_invalid_returns_422 tests/test_dashboard_html.py::test_set_theme_missing_body_returns_422 -v
```
Esperado: todos PASS.

- [ ] **Step 5: Suite completa — sem regressões**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/dashboard_html.py tests/test_dashboard_html.py
git commit -m "feat(theme): endpoint POST /set-theme com cookie HTTP-only"
```

---

## Chunk 3: Template e CSS overlay — data-theme + overlays tokenizados + toggle

**Files:**
- Modify: `src/agents/templates/base.html`
- Modify: `src/agents/static/dashboard.css`
- Test: `tests/test_dashboard_html.py` (append)

> **Nota de arquitetura:** Os rgba de backdrop (`rgba(0,0,0,0.45)` e `rgba(0,0,0,0.65)`) estão no `dashboard.css` dentro de `@media (max-width: 767px)`, não no HTML. A tokenização acontece no CSS. Os testes de overlay leem o arquivo CSS diretamente (mesmo padrão de `test_css_vars_root_defined`).

---

### Task 3: `data-theme` no `<html>` + overlays tokenizados no CSS

- [ ] **Step 1: Escrever os testes que FALHAM**

Adicionar ao final de `tests/test_dashboard_html.py`:

```python
# ---------------------------------------------------------------------------
# Light Theme — Template
# ---------------------------------------------------------------------------


def test_html_element_has_data_theme_default_dark(app_with_dashboard):
    """Sem cookie, <html> deve ter data-theme="dark"."""
    resp = app_with_dashboard.get("/dashboard")
    assert b'data-theme="dark"' in resp.content


def test_html_element_has_data_theme_light_with_cookie(app_with_dashboard):
    """Com cookie theme=light, <html> deve ter data-theme="light"."""
    app_with_dashboard.cookies.set("theme", "light")
    try:
        resp = app_with_dashboard.get("/dashboard")
        assert b'data-theme="light"' in resp.content
    finally:
        app_with_dashboard.cookies.clear()


def test_html_element_has_data_theme_dark_with_cookie(app_with_dashboard):
    """Com cookie theme=dark, <html> deve ter data-theme="dark"."""
    app_with_dashboard.cookies.set("theme", "dark")
    try:
        resp = app_with_dashboard.get("/dashboard")
        assert b'data-theme="dark"' in resp.content
    finally:
        app_with_dashboard.cookies.clear()


def test_css_sidebar_backdrop_uses_overlay_token():
    """dashboard.css deve usar var(--overlay-backdrop) no backdrop do sidebar."""
    css = _read_css()
    # Os backdrops mobile ficam no CSS, não no HTML
    assert "var(--overlay-backdrop)" in css
    assert css.count("var(--overlay-backdrop)") >= 3  # sidebar-backdrop + panel-backdrop + projects-backdrop


def test_css_sidebar_shadow_uses_overlay_shadow_token():
    """dashboard.css deve usar var(--overlay-shadow) no box-shadow do sidebar mobile."""
    css = _read_css()
    assert "var(--overlay-shadow)" in css


def test_css_no_hardcoded_backdrop_rgba_after_tokenization():
    """Os rgba(0,0,0,0.45) e rgba(0,0,0,0.65) não devem mais aparecer nos backdrops do CSS."""
    css = _read_css()
    # sidebar-backdrop, panel-backdrop e projects-backdrop devem usar tokens
    # (o wizard-overlay pode manter hardcoded — é intencional)
    # Verificamos que o CSS não tem backdrop rgba hardcoded fora do wizard
    media_mobile_start = css.find("@media (max-width: 767px)")
    media_mobile_end = css.find("@media (min-width: 768px)")
    mobile_section = css[media_mobile_start:media_mobile_end]
    assert "rgba(0,0,0,0.45)" not in mobile_section
    assert "rgba(0,0,0,0.65)" not in mobile_section
```

- [ ] **Step 2: Rodar e confirmar FALHA**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_html_element_has_data_theme_default_dark tests/test_dashboard_html.py::test_css_sidebar_backdrop_uses_overlay_token -v
```
Esperado: FAIL.

- [ ] **Step 3a: Implementar — `data-theme` no `<html>` em `base.html`**

Linha 3 atual em `src/agents/templates/base.html`:
```html
<html lang="pt-BR">
```
Substituir por:
```html
<html lang="pt-BR" data-theme="{{ request.cookies.get('theme', 'dark') }}">
```

- [ ] **Step 3b: Implementar — tokenizar rgba em `dashboard.css`**

Em `src/agents/static/dashboard.css`, dentro do bloco `@media (max-width: 767px)`:

Linha 81 — `#sidebar.sidebar-open box-shadow`:
```css
    box-shadow: 4px 0 24px rgba(0,0,0,0.65);
```
→ substituir por:
```css
    box-shadow: 4px 0 24px var(--overlay-shadow);
```

Linha 85 — `#sidebar-backdrop background`:
```css
    background: rgba(0,0,0,0.45); z-index: 99; cursor: pointer;
```
→ substituir por:
```css
    background: var(--overlay-backdrop); z-index: 99; cursor: pointer;
```

Linha 104 — `#panel-backdrop background`:
```css
    background: rgba(0,0,0,0.45); z-index: 48;
```
→ (primeira ocorrência após `#panel-backdrop`) substituir por:
```css
    background: var(--overlay-backdrop); z-index: 48;
```

Linha 122 — `#projects-backdrop background`:
```css
    background: rgba(0,0,0,0.45); z-index: 48;
```
→ (segunda ocorrência) substituir por:
```css
    background: var(--overlay-backdrop); z-index: 48;
```

> `#wizard-overlay` (`rgba(0,0,0,.75)` e `rgba(0,0,0,.5)`) em `base.html` são intencionalmente mantidos hardcoded — ver spec.

- [ ] **Step 4: Rodar e confirmar PASS**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_html_element_has_data_theme_default_dark tests/test_dashboard_html.py::test_html_element_has_data_theme_light_with_cookie tests/test_dashboard_html.py::test_css_sidebar_backdrop_uses_overlay_token tests/test_dashboard_html.py::test_css_sidebar_shadow_uses_overlay_shadow_token tests/test_dashboard_html.py::test_css_no_hardcoded_backdrop_rgba_after_tokenization -v
```

- [ ] **Step 5: Suite completa — sem regressões**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/agents/templates/base.html src/agents/static/dashboard.css tests/test_dashboard_html.py
git commit -m "feat(theme): data-theme no <html> + overlays tokenizados no CSS"
```

---

### Task 4: Toggle button no topbar

- [ ] **Step 1: Escrever os testes que FALHAM**

Adicionar ao final de `tests/test_dashboard_html.py`:

```python
def test_theme_toggle_button_present(app_with_dashboard):
    """Topbar deve conter o botão de toggle de tema."""
    resp = app_with_dashboard.get("/dashboard")
    assert b"theme-toggle" in resp.content
    assert b"toggleTheme" in resp.content


def test_theme_toggle_icon_dark_by_default(app_with_dashboard):
    """Sem cookie, botão deve mostrar ícone de dark (☾)."""
    resp = app_with_dashboard.get("/dashboard")
    # ☾ encoded as UTF-8
    assert "☾".encode() in resp.content


def test_theme_toggle_icon_sun_when_light(app_with_dashboard):
    """Com cookie theme=light, botão deve mostrar ícone de light (☀)."""
    app_with_dashboard.cookies.set("theme", "light")
    resp = app_with_dashboard.get("/dashboard")
    app_with_dashboard.cookies.clear()
    assert "☀".encode() in resp.content


def test_theme_toggle_js_rollback_present(app_with_dashboard):
    """JS de toggleTheme deve conter lógica de rollback (dataset.theme = current)."""
    resp = app_with_dashboard.get("/dashboard")
    html = resp.text
    assert "toggleTheme" in html
    # rollback: reassign current theme on failure
    assert "html.dataset.theme = current" in html
```

- [ ] **Step 2: Rodar e confirmar FALHA**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_theme_toggle_button_present tests/test_dashboard_html.py::test_theme_toggle_icon_dark_by_default -v
```
Esperado: FAIL.

- [ ] **Step 3: Implementar — botão + JS em `base.html`**

**3a. Botão no topbar:** Em `base.html`, o bloco `{% block topbar %}` é sobrescrito por cada página. O toggle precisa ficar fora do bloco, diretamente no `#app-topbar`.

> **Nota:** Adicionar `display:flex` ao `#app-topbar` é uma mudança de layout intencional e necessária para posicionar o toggle à direita. O bloco `{% block topbar %}` é envolto num `<div style="flex:1;">` para preservar o layout do conteúdo existente. Os testes existentes verificam `height:44px` no interior do topbar — esse teste continuará passando pois o conteúdo interno não muda.

Modificar o `#app-topbar` em `src/agents/templates/base.html` de:

```html
<div id="app-topbar"
     style="flex-shrink:0;background:var(--bg-chrome);">
  {% block topbar %}{% endblock %}
</div>
```

Para:

```html
<div id="app-topbar"
     style="flex-shrink:0;background:var(--bg-chrome);display:flex;align-items:center;justify-content:space-between;">
  <div style="flex:1;">{% block topbar %}{% endblock %}</div>
  <button id="theme-toggle"
          onclick="toggleTheme()"
          aria-label="Alternar tema"
          title="Alternar tema"
          style="background:transparent;border:none;color:var(--text-secondary);
                 cursor:pointer;font-size:16px;padding:4px 10px;line-height:1;
                 font-family:inherit;border-radius:3px;transition:color .15s;
                 flex-shrink:0;margin-right:8px;"
          onmouseover="this.style.color='var(--text-primary)'"
          onmouseout="this.style.color='var(--text-secondary)'">{{ '☀' if request.cookies.get('theme', 'dark') == 'light' else '☾' }}</button>
</div>
```

**3b. Função JS `toggleTheme`:** Adicionar antes do `</body>` em `base.html` (após o `<script>` do wizard):

```html
<script>
  function toggleTheme() {
    var html = document.documentElement;
    var current = html.dataset.theme || 'dark';
    var next = current === 'light' ? 'dark' : 'light';
    html.dataset.theme = next;
    document.getElementById('theme-toggle').textContent = next === 'light' ? '☀' : '☾';
    fetch('/set-theme', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'theme=' + next
    }).then(function(r) {
      if (!r.ok) {
        html.dataset.theme = current;
        document.getElementById('theme-toggle').textContent = current === 'light' ? '☀' : '☾';
      }
    }).catch(function() {
      html.dataset.theme = current;
      document.getElementById('theme-toggle').textContent = current === 'light' ? '☀' : '☾';
    });
  }
</script>
```

- [ ] **Step 4: Rodar e confirmar PASS**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/test_dashboard_html.py::test_theme_toggle_button_present tests/test_dashboard_html.py::test_theme_toggle_icon_dark_by_default tests/test_dashboard_html.py::test_theme_toggle_icon_sun_when_light tests/test_dashboard_html.py::test_theme_toggle_js_rollback_present -v
```

- [ ] **Step 5: Suite completa + suite de macros**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/ -v
```
Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agents/templates/base.html tests/test_dashboard_html.py
git commit -m "feat(theme): toggle ☀/☾ no topbar com JS rollback"
```

---

## Verificação Final

- [ ] **Rodar suite completa**

```bash
cd /Users/vini/Developer/agents && python -m pytest tests/ -v
```
Esperado: zero falhas.

- [ ] **Checar lint**

```bash
cd /Users/vini/Developer/agents && python -m ruff check src/ tests/ 2>/dev/null || echo "ruff not available" && python -m flake8 src/ tests/ 2>/dev/null || echo "flake8 not available"
```
