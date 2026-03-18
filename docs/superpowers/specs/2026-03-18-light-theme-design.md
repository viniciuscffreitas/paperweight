# Light Theme — Design Spec

**Data:** 2026-03-18
**Status:** Aprovado

## Objetivo

Adicionar um light theme warm (tons creme/areia) ao app paperweight, ativável via toggle permanente no header, persistido em cookie HTTP-only.

## Decisões de Design

- **Ativação:** atributo `data-theme="light"` no `<html>`, injetado pelo Jinja2 via cookie
- **Persistência:** cookie `theme` (HTTP-only, path=`/`, max-age=1 ano)
- **Fallback:** ausência do cookie → `data-theme="dark"` (comportamento atual inalterado)
- **Toggle:** botão fixo no topbar, chama `POST /set-theme`, JS aplica `data-theme` sem reload
- **Ícone do toggle:** mostra o estado *atual* (`☀` = light ativo, `☾` = dark ativo)
- **httponly note:** o cookie `theme` é `httponly=True` — JS **não pode** ler via `document.cookie`. O source of truth no cliente é `document.documentElement.dataset.theme` (DOM attribute), sempre.

## Paleta Warm Light

| Token                | Dark (atual)  | Light (novo)  |
|----------------------|---------------|---------------|
| `--bg-chrome`        | `#0d0f18`     | `#f5f0e8`     |
| `--bg-content`       | `#111520`     | `#fdfaf4`     |
| `--bg-elevated`      | `#1e2130`     | `#ede8df`     |
| `--bg-overlay`       | `#1a1d27`     | `#e8e2d8`     |
| `--border-subtle`    | `#1e2130`     | `#ddd8ce`     |
| `--border-default`   | `#2d3142`     | `#c8c2b8`     |
| `--border-strong`    | `#4b5563`     | `#a89e92`     |
| `--text-primary`     | `#e5e7eb`     | `#1a1612`     |
| `--text-secondary`   | `#9ca3af`     | `#5c5248`     |
| `--text-muted`       | `#6b7280`     | `#8a8078`     |
| `--text-disabled`    | `#4b5563`     | `#b0a89e`     |
| `--text-placeholder` | `#374151`     | `#c0b8ae`     |
| `--accent`           | `#3b82f6`     | `#2563eb`     |
| `--accent-bg`        | `#1e3a5f`     | `#dbeafe`     |
| `--accent-hover`     | `#1d4ed8`     | `#1e40af`     |
| `--bg-task-success`  | `#1a3a1a`     | `#dcfce7`     |
| `--bg-task-error`    | `#2a1a1a`     | `#fee2e2`     |
| `--bg-task-hover`    | `#1a1d27`     | `#ede8df`     |

Status colors (`--status-*`) são sobrescritos no light theme com versões mais escuras para garantir WCAG 3:1 de contraste sobre o fundo creme. Os valores do dark theme (`#4ade80`, `#f87171` etc.) falham o threshold de 3:1 sobre `#fdfaf4`.

| Token                | Dark (atual)  | Light (novo)  |
|----------------------|---------------|---------------|
| `--status-running`   | `#3b82f6`     | `#1d4ed8`     |
| `--status-success`   | `#4ade80`     | `#15803d`     |
| `--status-error`     | `#f87171`     | `#b91c1c`     |
| `--status-warning`   | `#fb923c`     | `#c2410c`     |
| `--status-neutral`   | `#6b7280`     | `#57534e`     |

### Overlays rgba (mobile)

Os backdrops mobile usam `rgba(0,0,0,0.45)` hardcoded (intencionalmente não tokenizados — ver comentário no CSS). No light theme esses overlays ficam visualmente incorretos sobre o fundo creme. Solução: tokenizar apenas esses valores de overlay usando um seletor `[data-theme="light"]`:

```css
/* no bloco [data-theme="light"] */
--overlay-backdrop: rgba(80, 60, 40, 0.35);
--overlay-shadow:   rgba(80, 60, 40, 0.50);
```

Nos usos inline em `base.html` (sidebar-backdrop, panel-backdrop, projects-backdrop, sidebar box-shadow mobile), substituir as strings `rgba(0,0,0,...)` por `var(--overlay-backdrop)` e `var(--overlay-shadow)` respectivamente. No bloco `:root` dark, definir os mesmos tokens com os valores atuais.

**Wizard overlay (`#wizard-overlay`) — intencionalmente excluído do escopo:** as duas ocorrências hardcoded em `base.html` (`rgba(0,0,0,.75)` backdrop e `rgba(0,0,0,.5)` box-shadow do card) são modais que cobrem toda a tela. No light theme, um overlay escuro sobre fundo claro é visualmente correto e não constitui regressão — o contraste do modal sobre o conteúdo fica adequado. Esses valores **não são tokenizados** nesta iteração.

## Arquitetura

### 1. CSS (`dashboard.css`)

Adicionar tokens de overlay no `:root`:
```css
:root {
  /* ... tokens existentes ... */
  --overlay-backdrop: rgba(0,0,0,0.45);
  --overlay-shadow:   rgba(0,0,0,0.65);
}
```

Adicionar bloco após `:root`:
```css
[data-theme="light"] {
  /* todos os tokens da tabela acima + */
  --overlay-backdrop: rgba(80,60,40,0.35);
  --overlay-shadow:   rgba(80,60,40,0.50);
}
```

### 2. Template Base (`base.html`)

Tag `<html>`:
```html
<html lang="pt-BR" data-theme="{{ request.cookies.get('theme', 'dark') }}">
```

Substituir `rgba(0,0,0,0.45)` e `rgba(0,0,0,0.65)` por `var(--overlay-backdrop)` e `var(--overlay-shadow)` nos estilos inline dos backdrops mobile.

### 3. Endpoint FastAPI (`dashboard_html.py`)

Registrado dentro de `setup_dashboard(app, state)` como `@app.post(...)` (padrão do arquivo).

**Import necessário:** adicionar `Form, HTTPException` ao import existente de `fastapi`:
```python
from fastapi import ..., Form, HTTPException
```

```python
@app.post("/set-theme")
async def set_theme(response: Response, theme: str = Form(...)):
    if theme not in ("light", "dark"):
        raise HTTPException(status_code=422, detail="Invalid theme")
    response.set_cookie("theme", theme, max_age=31536000, path="/", httponly=True, samesite="lax")
    return {"ok": True}
```

### 4. Toggle Button + JS (`base.html`)

Adicionado no `#app-topbar`. Ícone mostra o estado atual: `☀` quando light, `☾` quando dark.

```html
<button id="theme-toggle"
        onclick="toggleTheme()"
        aria-label="Alternar tema"
        style="background:transparent;border:none;color:var(--text-secondary);
               cursor:pointer;font-size:16px;padding:4px 8px;line-height:1;
               font-family:inherit;border-radius:3px;transition:color .15s;"
        onmouseover="this.style.color='var(--text-primary)'"
        onmouseout="this.style.color='var(--text-secondary)'">
  {{ '☀' if request.cookies.get('theme', 'dark') == 'light' else '☾' }}
</button>
```

JS inline no final do `base.html`:
```js
function toggleTheme() {
  var html = document.documentElement;
  var current = html.dataset.theme || 'dark';
  var next = current === 'light' ? 'dark' : 'light';
  // rollback se o POST falhar
  html.dataset.theme = next;
  document.getElementById('theme-toggle').textContent = next === 'light' ? '☀' : '☾';
  fetch('/set-theme', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'theme=' + next
  }).then(function(r) {
    if (!r.ok) {
      // rollback DOM
      html.dataset.theme = current;
      document.getElementById('theme-toggle').textContent = current === 'light' ? '☀' : '☾';
    }
  }).catch(function() {
    // rollback DOM em falha de rede
    html.dataset.theme = current;
    document.getElementById('theme-toggle').textContent = current === 'light' ? '☀' : '☾';
  });
}
```

## Telas Cobertas

- Dashboard (`dashboard.html`)
- Hub de projetos (`hub/panel.html`, `hub/activity.html`, `hub/tasks.html`, `hub/runs.html`)
- Setup wizard (`setup/step2.html`, modal inline em `base.html`)

## Testes

### CSS
- Bloco `[data-theme="light"]` define todos os tokens listados na tabela
- Token `--overlay-backdrop` e `--overlay-shadow` definidos em `:root` e sobrescritos em `[data-theme="light"]`

### Endpoint
- `POST /set-theme` com `theme=light` → seta cookie `theme=light`, retorna `{"ok": true}`
- `POST /set-theme` com `theme=dark` → seta cookie `theme=dark`
- `POST /set-theme` com valor inválido → 422
- Cookie tem `httponly=True`, `samesite=lax`, `max_age=31536000`

### Template
- Cookie `theme=light` → `<html data-theme="light">`
- Cookie ausente → `<html data-theme="dark">`
- Ícone renderizado: `☀` quando `theme=light`, `☾` quando dark/ausente

### JS Toggle
- Clique quando dark → `data-theme` vira `light`, ícone vira `☀`
- Clique quando light → `data-theme` vira `dark`, ícone vira `☾`
- Se POST retorna não-ok → DOM é revertido ao estado anterior
- Se fetch lança exceção → DOM é revertido ao estado anterior

### Regressão
- Sem cookie → comportamento visual idêntico ao atual (dark)
- Nenhum componente HTML tem sua estrutura alterada

## O que NÃO muda

- Estrutura HTML de qualquer componente
- Valores dos tokens `--status-*`
- Lógica de negócio (executor, scheduler, webhooks)
- Seletores CSS de componentes (só tokens e overlays mudam)
