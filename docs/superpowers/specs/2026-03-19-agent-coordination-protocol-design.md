# Design: Paperweight Coordination Protocol (PCP)

**Data:** 2026-03-19
**Status:** Em revisão

---

## Problema

O paperweight já executa múltiplos agentes em paralelo (até 3 global, 2 por repo) com worktrees isolados. Mas os agentes são **cegos** — cada um roda sem saber o que os outros estão fazendo. Quando dois agentes editam o mesmo arquivo, o resultado é PRs conflitantes que exigem merge manual.

O Replit Agent 4 resolveu isso com sub-agentes coordenados que detectam overlap de escopo e reconciliam conflitos automaticamente. Cursor tentou locking e falhou (agentes seguravam locks demais, reduzindo 20 agentes para throughput de 2-3). O sucesso veio de hierarquia Planner/Worker/Judge.

### Requisitos

1. Agentes devem ter **awareness em tempo real** do que outros agentes estão fazendo
2. Conflitos de arquivo devem ser **detectados e resolvidos automaticamente**, sem intervenção humana
3. Quando dois agentes precisam do mesmo arquivo, um **mediator agent** especializado deve fazer ambas as mudanças de forma coerente
4. O sistema deve ser **resiliente** a agentes que ignoram o protocolo (fallback layers)
5. Zero perda de trabalho — no pior caso, PRs separados com notificação

### Restrição técnica fundamental

O `claude -p` é fire-and-forget. Não aceita prompts adicionais mid-run. A única comunicação possível com um agente em execução é **via filesystem** — o agente já sabe ler e escrever arquivos.

---

## Pesquisa: Prior Art

| Projeto | Abordagem | Lição |
|---------|-----------|-------|
| **Replit Agent 4** | Manager → Editor sub-agents → Verifier. Reconciliação por sub-agent especializado. | Mediator pattern funciona. Ambiente controlado ajuda. |
| **Claude Code Agent Teams** | JSON inboxes em disco (`~/.claude/teams/`). File locking para task claiming. | Filesystem messaging é viável. File ownership > locking. |
| **OpenCode** | JSONL append-only (O(1) write). Event-driven wake. Full mesh peer-to-peer. | JSONL resolve race condition de JSON arrays. |
| **Cursor** | FALHOU: locking (throughput caiu 90%). FALHOU: optimistic concurrency (agentes ficaram risk-averse). SUCESSO: Planner/Worker/Judge. | Claims devem ter TTL agressivo. Hierarquia > igualdade. |
| **Overstory** | SQLite WAL messaging (1-5ms). 4-tier conflict resolution. Tiered health monitoring. | SQLite WAL é rápido. Health monitoring é essencial. |
| **tick-md** | TICK.md como backbone. File locking no claim. Dependency tracking. | Race conditions são reais (v1.2.0 fix). |

---

## Solução: Paperweight Coordination Protocol (PCP)

### Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    CoordinationBroker                        │
│  (Python puro, roda dentro do paperweight server)           │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐             │
│  │  Claim    │  │  Inbox   │  │  Mediator    │             │
│  │  Registry │  │  Poller  │  │  Spawner     │             │
│  └──────────┘  └──────────┘  └──────────────┘             │
│       ▲              ▲              │                       │
│       │              │              ▼                       │
│  stream-json    filesystem    executor.run_task()           │
│  events         polling                                     │
└───┬─────────────┬────────────────┬──────────────────────────┘
    │             │                │
    ▼             ▼                ▼
┌────────┐  ┌────────┐      ┌────────────┐
│Agent A │  │Agent B │      │ Mediator C │
│worktree│  │worktree│      │ worktree   │
│  /.pw/ │  │  /.pw/ │      │            │
│  state │  │  state │      │            │
│  inbox │  │  inbox │      │            │
│  outbox│  │  outbox│      │            │
└────────┘  └────────┘      └────────────┘
```

### O Protocolo de Coordenação

Cada worktree recebe um diretório `/.paperweight/` com 3 arquivos:

| Arquivo | Formato | Escritor | Leitor | Propósito |
|---------|---------|----------|--------|-----------|
| `state.json` | JSON | Broker | Agente | Estado global: runs ativos, claims, mediations |
| `inbox.jsonl` | JSONL (append-only) | Agente | Broker | Mensagens agente → broker |
| `outbox.jsonl` | JSONL (append-only) | Broker | Agente | Respostas broker → agente |

**Por que JSONL em vez de JSON para inbox/outbox:**
- Append-only: O(1) write, sem read-modify-write race condition (lição do OpenCode)
- O agente só precisa fazer `echo '{"type":"..."}' >> inbox.jsonl`
- O broker lê incrementalmente (seek to last position)
- `state.json` permanece JSON porque é um snapshot completo reescrito pelo broker

### Ciclo de vida completo

```
1.  Executor cria worktree para Agent A
2.  Broker escreve /.paperweight/state.json com estado global
3.  Executor injeta "coordination preamble" no prompt de Agent A
4.  Agent A inicia, lê state.json (vazio ou com runs existentes)
5.  Agent A edita users.py → stream-json emite content_block_start:tool_use:Edit
6.  Broker intercepta evento, registra claim: {A: "users.py", type: HARD}
7.  Broker reescreve state.json em TODOS os worktrees ativos
8.  Executor cria worktree para Agent B (nova task)
9.  Agent B inicia, lê state.json → vê "users.py claimed by A"
10. Agent B precisa de users.py → escreve em inbox.jsonl:
    {"type":"need_file","file":"src/api/users.py","intent":"add auth middleware"}
11. Broker lê inbox de B, detecta conflito com A
12. Broker spawna Mediator Agent C:
    - Novo worktree baseado no base_branch
    - Prompt contém intents de A e B + conteúdo atual do arquivo
    - Budget limitado ($1.00), timeout 5min
13. Mediator C faz ambas as mudanças coerentemente, commita
14. Broker escreve outbox.jsonl de A e B:
    {"type":"file_mediated","file":"src/api/users.py","action":"skip_file"}
15. A e B leem outbox na próxima verificação, pulam users.py
16. Quando A e B terminam, broker faz rebase sobre branch do mediator
17. PRs criados normalmente com as mudanças de mediação integradas
```

---

## Claim System

### State Machine

```
UNCLAIMED ──→ SOFT (Read)
              │
              ▼
           HARD (Edit/Write)
              │
              ├──→ CONTESTED (outro agente precisa via inbox)
              │       │
              │       ▼
              │    MEDIATING (mediator spawned)
              │       │
              │    ┌──┴──┐
              │    ▼     ▼
              │  DONE  FAILED → fallback: PRs separados
              │    │
              ▼    ▼
           RELEASED
```

### Detecção via stream-json (event-driven, zero polling)

O `claude -p --output-format stream-json` emite **message-level events** (não SSE deltas). Cada `assistant` event contém `tool_use` blocks completos:

```json
{"type": "assistant", "message": {"content": [
  {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/api/users.py", "old_string": "...", "new_string": "..."}}
]}}
```

O broker intercepta eventos `assistant` com `tool_use` blocks, extrai `input.file_path` de `Edit`, `Write`, e `Read` calls. **Nota**: o `streaming.py` atual trunca input a 200 chars — precisa ser estendido para expor `file_path` completo via novo campo `StreamEvent.file_path`.

**Path normalization**: file_path vem como caminho absoluto do worktree (ex: `/tmp/agents/run-id/src/api/users.py`). O broker normaliza para repo-relative: `os.path.relpath(absolute_path, worktree_root)`.

### Claim TTL (lição do Cursor)

Claims expiram após **300s sem atividade** (nenhum novo stream-json event do agente owner). Previne o problema do Cursor onde agentes seguravam locks indefinidamente. O broker usa **stream event activity** como health signal primário (mais confiável que heartbeats via inbox).

```python
# Pseudo-código do TTL check
if claim.status == HARD and (now - claim.last_activity) > claim_timeout:
    claim.status = RELEASED
    update_all_state_files()
```

`last_activity` é atualizado a cada stream-json event do agent owner, não apenas em edits.
```

### Detecção de conflitos

| Trigger | Ação |
|---------|------|
| Agent B faz Edit em arquivo HARD-claimed por A (detectado via stream-json) | Status → CONTESTED, spawn mediator retroativo |
| Agent B escreve `need_file` no inbox para arquivo claimed por A | Status → CONTESTED, spawn mediator proativo |
| Deadlock: A precisa arquivo de B, B precisa arquivo de A | Broker detecta ciclo, spawna mediator único para ambos |
| Agent termina, tem claims ativos | Release all claims, update state files |

---

## Mediator Agent

### Quando é spawned

1. **Proativo**: Broker lê `need_file` no inbox para arquivo com hard claim ativo
2. **Retroativo**: Broker detecta via stream-json que dois agentes editaram o mesmo arquivo
3. **Deadlock**: Broker detecta dependência circular entre claims

### Prompt do mediator

```markdown
## Mediation Task

Two agents need changes to the same file(s). Apply BOTH changes coherently.

### Agent A — "{task_a.description}"
Original task intent: "{task_a.intent}"
What Agent A needs in {file}: "{inbox_a.intent_for_file}"
Changes Agent A already made (if any): {diff_a_for_file}

### Agent B — "{task_b.description}"
Original task intent: "{task_b.intent}"
What Agent B needs in {file}: "{inbox_b.intent_for_file or task_b.intent}"
(If no inbox message exists — retroactive conflict — intent is synthesized from the task description and git diff of what the agent already changed)

### Current file (base branch):
{file_content_from_base}

### Instructions:
1. Understand what BOTH agents need for this file
2. Apply both changes coherently — they should work together
3. If the changes are incompatible, apply the most critical one and document the other as a TODO
4. Write tests if the file has associated test files
5. Commit: "mediation({file_basename}): {summary}"
6. Touch ONLY the contested file(s) — nothing else
```

### Orçamento e limites

```yaml
mediator:
  model: claude-sonnet-4-6    # não precisa de opus para merge
  max_cost_usd: 1.00          # mediator trabalha em 1-2 arquivos
  timeout_minutes: 5
  max_concurrent: 2            # evita explosão de custo
```

### Integração com branches

```
base_branch (main)
  ├── agents/task-a-20260319-100000  (Agent A's branch)
  ├── agents/task-b-20260319-100500  (Agent B's branch)
  └── agents/mediation-med-001       (Mediator's branch)

Após mediator completar:
  1. Rebase branch de A sobre mediation branch
     - Para arquivos mediados: git checkout --theirs (aceita versão do mediator)
     - O mediator já incorporou o intent de A, então sua versão é autoritativa
  2. Rebase branch de B sobre mediation branch (mesma estratégia)
  3. Se rebase falha mesmo com --theirs → PRs separados com nota de conflito
```

### Worktree lifecycle com coordination

Quando `coordination.enabled = true`, o executor **NÃO deleta worktrees no `finally` block**. Em vez disso:

1. Executor sinaliza `deregister_run()` ao broker
2. Broker verifica `has_pending_mediations(run_id)`
3. Se tem mediações pendentes: worktree persiste até mediação completar + rebase
4. Broker chama `cleanup_worktree(run_id)` após rebase concluído
5. Se não tem mediações: cleanup imediato (comportamento atual)

Isso evita o conflito onde o executor deletava o worktree antes do rebase.

---

## Protocol Schema

### `state.json` (broker → agente)

```json
{
  "protocol_version": 1,
  "updated_at": "2026-03-19T10:30:00.000Z",
  "this_run_id": "myapp-fix-auth-20260319-100500-b7c2d1",
  "active_runs": {
    "myapp-issue-resolver-20260319-100000-a3f1b2": {
      "task": "issue-resolver",
      "intent": "Implement pagination for /api/users",
      "files_claimed": ["src/api/users.py", "tests/test_users.py"],
      "files_completed": ["src/models/pagination.py"],
      "status": "running",
      "started_at": "2026-03-19T10:00:00.000Z"
    }
  },
  "claims": {
    "src/api/users.py": {
      "owner_run": "myapp-issue-resolver-20260319-100000-a3f1b2",
      "type": "hard",
      "since": "2026-03-19T10:02:00.000Z"
    }
  },
  "mediations": {
    "med-001": {
      "files": ["src/api/users.py"],
      "requester_runs": ["run-a-id", "run-b-id"],
      "status": "in_progress",
      "detail": "Mediator applying pagination + auth changes"
    }
  }
}
```

### `inbox.jsonl` (agente → broker, append-only)

Tipos de mensagem:

| type | Campos | Quando |
|------|--------|--------|
| `need_file` | `file`, `intent`, `priority` | Agente precisa de arquivo claimed |
| `edit_complete` | `file` | Agente terminou de editar arquivo |
| `skip_file` | `file`, `reason` | Agente acatou instrução de skip |
| `heartbeat` | — | A cada ~10 tool calls, prova que agente está vivo |
| `escalation` | `message` | Agente travou e pede ajuda |

```jsonl
{"type":"need_file","file":"src/api/users.py","intent":"add auth middleware","priority":"required","ts":"2026-03-19T10:03:00.000Z"}
{"type":"heartbeat","ts":"2026-03-19T10:04:00.000Z"}
{"type":"edit_complete","file":"src/middleware/auth.py","ts":"2026-03-19T10:05:00.000Z"}
```

### `outbox.jsonl` (broker → agente, append-only)

Tipos de mensagem:

| type | Campos | Quando |
|------|--------|--------|
| `file_mediated` | `file`, `mediation_id`, `action`, `detail` | Mediator resolveu o arquivo |
| `file_released` | `file`, `detail` | Arquivo liberado (owner terminou) |
| `delegate_accepted` | `file`, `mediation_id` | Pedido de delegação aceito |
| `conflict_warning` | `file`, `other_run`, `detail` | Aviso de conflito iminente |

```jsonl
{"type":"file_mediated","file":"src/api/users.py","mediation_id":"med-001","action":"skip_file","detail":"Mediator applied both changes coherently","ts":"2026-03-19T10:06:00.000Z"}
{"type":"file_released","file":"tests/test_users.py","detail":"Agent A finished","ts":"2026-03-19T10:07:00.000Z"}
```

### Escrita atômica

- `state.json`: write to `.state.json.tmp` → `os.rename()` (atômico em POSIX)
- `inbox.jsonl` / `outbox.jsonl`: append direto (O(1), sem race condition para single writer por arquivo)
- Broker lê inbox com seek incremental (guarda last read position por run_id)
- **Debouncing**: state.json writes são coalesced em janelas de 200ms para evitar I/O excessivo durante edits rápidos. Claims acumulam no registry em memória e são flushed periodicamente.

---

## Coordination Preamble (Prompt Injection)

Injetado no início do prompt de todo agente em modo coordenado:

```markdown
## Coordinated Mode — Paperweight Protocol

You are running alongside other AI agents on the same repository. Each agent has
an isolated git worktree, but you share the same codebase.

### MANDATORY — Before editing ANY file:
1. Read `/.paperweight/state.json` to check `claims`
2. If the file is claimed by another agent: DO NOT edit it
3. Instead, append to `/.paperweight/inbox.jsonl`:
   {"type":"need_file","file":"<path>","intent":"<what you need to do>"}
4. Continue with OTHER files. Check `/.paperweight/outbox.jsonl` periodically.

### After editing a file:
Append to `/.paperweight/inbox.jsonl`:
{"type":"edit_complete","file":"<path>"}

### After each major step, read `/.paperweight/outbox.jsonl`:
- `file_mediated`: A mediator handled this file. SKIP it entirely.
- `file_released`: File available. You may edit it now.

### Heartbeat:
Every ~10 tool calls, append to inbox.jsonl: {"type":"heartbeat"}

### Rules:
- NEVER force-edit a claimed file
- If ALL your files are claimed, work on tests, docs, or config
- The orchestrator resolves conflicts automatically
```

### Por que o agente vai obedecer

1. O prompt instruction é claro e no topo do contexto (alta saliência)
2. O agente tem incentivo: evitar conflitos = menos retrabalho
3. **Fallback**: mesmo se ignorar, broker detecta via stream-json e spawna mediator retroativo

---

## Módulos & Integração

### Novos módulos

```
src/agents/coordination/
├── __init__.py
├── broker.py          # CoordinationBroker — cérebro central
├── claims.py          # ClaimRegistry — state machine + TTL
├── protocol.py        # I/O atômico de state/inbox/outbox
├── mediator.py        # MediatorSpawner — cria mediator agents
└── models.py          # Pydantic: Claim, Mediation, CoordMessage, CoordConfig
```

### Integração com módulos existentes

| Módulo | Mudança |
|--------|---------|
| `executor.py` | Cria `/.paperweight/`, registra run no broker, injeta preamble, faz rebase pós-mediação |
| `streaming.py` | Adiciona campo `file_path` ao `StreamEvent`, extraído de `tool_use` blocks em `assistant` events. Remove truncamento de 200 chars para tool inputs quando coordination enabled. Parseia múltiplos content blocks por mensagem (hoje retorna só o primeiro). |
| `app_state.py` | Adiciona `broker: CoordinationBroker` |
| `main.py` | Inicializa broker no startup, hooks broker no pipeline de broadcast |
| `config.py` | Adiciona `CoordinationConfig` ao `AppConfig` |
| `history.py` | 3 novas tabelas: `file_claims`, `mediations`, `coordination_log` |

### `broker.py` — Interface principal

```python
class CoordinationBroker:
    claims: ClaimRegistry
    mediator_spawner: MediatorSpawner
    active_worktrees: dict[str, Path]  # run_id → worktree path

    async def start(self) -> None
    async def stop(self) -> None
    async def register_run(self, run_id: str, worktree: Path, intent: str) -> None
    async def deregister_run(self, run_id: str) -> None
    async def on_stream_event(self, run_id: str, event: StreamEvent) -> None
    async def has_pending_mediations(self, run_id: str) -> bool
    async def wait_mediations(self, run_id: str, timeout: float) -> None
```

### `claims.py` — State machine

```python
class ClaimRegistry:
    async def soft_claim(self, run_id: str, file_path: str) -> None
    async def hard_claim(self, run_id: str, file_path: str) -> Claim | None  # returns conflict
    async def release(self, run_id: str, file_path: str) -> None
    async def release_all(self, run_id: str) -> None
    async def check_ttl(self) -> list[Claim]  # returns expired claims
    def get_claims_for_run(self, run_id: str) -> list[Claim]
    def get_claim_for_file(self, file_path: str) -> Claim | None
    def detect_deadlock(self) -> list[list[str]]  # groups of deadlocked run_ids (DFS cycle detection on waits-for graph)
```

### `protocol.py` — I/O de filesystem

```python
def write_state(worktree: Path, state: dict) -> None  # atomic write via tmp+rename
def read_inbox(worktree: Path, from_position: int) -> tuple[list[dict], int]  # incremental
def append_outbox(worktree: Path, message: dict) -> None  # append JSONL line
def init_coordination_dir(worktree: Path) -> None  # create /.paperweight/ with empty files
```

### `mediator.py` — Spawner

```python
class MediatorSpawner:
    async def spawn(
        self,
        file_paths: list[str],
        run_a: str, intent_a: str,
        run_b: str, intent_b: str,
        repo_path: Path,
        base_branch: str,
    ) -> Mediation
    async def wait_completion(self, mediation_id: str, timeout: float) -> MediationResult
```

---

## Schema de dados (SQLite)

### Nova tabela: `file_claims`

```sql
PRAGMA foreign_keys = ON;  -- necessário para FK enforcement no SQLite

CREATE TABLE file_claims (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    file_path TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK(claim_type IN ('soft','hard')),
    status TEXT NOT NULL CHECK(status IN ('active','contested','mediating','released','completed')),
    claimed_at REAL NOT NULL,
    last_activity REAL NOT NULL,  -- atualizado a cada stream event do owner
    released_at REAL,
    UNIQUE(run_id, file_path)
);
CREATE INDEX idx_claims_file ON file_claims(file_path, status);
CREATE INDEX idx_claims_run ON file_claims(run_id, status);
```

### Nova tabela: `mediations`

```sql
CREATE TABLE mediations (
    id TEXT PRIMARY KEY,
    file_paths TEXT NOT NULL,
    requester_run_ids TEXT NOT NULL,
    mediator_run_id TEXT REFERENCES runs(id),
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
    created_at REAL NOT NULL,
    completed_at REAL
);
```

### Nova tabela: `coordination_log`

```sql
CREATE TABLE coordination_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('inbox','outbox','broker')),
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX idx_coordlog_run ON coordination_log(run_id, timestamp);
```

---

## Config

Nova seção em `config.yaml`:

```yaml
coordination:
  enabled: false               # opt-in, não quebra instalações existentes
  mode: full-mesh              # off | awareness-only | full-mesh
  claim_timeout_seconds: 300   # TTL agressivo (lição Cursor)
  poll_interval_ms: 500        # frequência de leitura dos inbox files
  auto_rebase: true            # rebase branches após mediação
  mediator:
    model: claude-sonnet-4-6
    max_cost_usd: 1.00
    timeout_minutes: 5
    max_concurrent: 2
```

Nova seção em `models.py` (Pydantic):

```python
class MediatorConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    max_cost_usd: float = 1.00
    timeout_minutes: int = 5
    max_concurrent: int = 2

class CoordinationConfig(BaseModel):
    enabled: bool = False
    mode: str = "full-mesh"
    claim_timeout_seconds: int = 300
    poll_interval_ms: int = 500
    auto_rebase: bool = True
    mediator: MediatorConfig = MediatorConfig()
```

---

## Resiliência: 4 camadas de fallback

O protocolo depende do agente ser obediente. Ele pode não ser. Cada camada protege a seguinte:

### Camada 1: Prompt (proativo)
- Agente lê state.json, evita conflitos
- **Eficácia estimada**: ~50-60% para protocolo completo (LLMs seguem "read state.json before edit" com alta probabilidade, mas heartbeats e outbox polling são frequentemente ignorados). O que importa: mesmo compliance parcial (só ler state.json) já evita a maioria dos conflitos proativamente.

### Camada 2: Stream-json detection (retroativo)
- Broker detecta edits reais em arquivos claimed via stream-json events
- Spawna mediator RETROATIVO mesmo que agente não tenha pedido
- **Eficácia**: ~99% (event-driven, não depende do agente)

### Camada 3: Post-hoc git rebase
- Após ambos os agentes terminarem, tenta rebase automático
- Se conflito no rebase → PRs separados com nota
- **Eficácia**: 100% para detectar conflitos

### Camada 4: Human notification
- Slack/Discord: "Agents A e B têm conflito em X. PRs separados criados."
- **Eficácia**: 100% (humano resolve)

**Garantia**: O sistema NUNCA perde trabalho. No pior caso, PRs separados.

---

## Observabilidade (Dashboard)

### Nova seção "Coordination" no dashboard

| Componente | O que mostra |
|------------|-------------|
| **Claim Map** | Grid arquivo × agente, cor por status |
| **Timeline** | Eventos de coordenação em tempo real via WebSocket |
| **Mediation Cards** | Status de cada mediação: agentes, arquivo, progresso |
| **Conflict Heat Map** | Arquivos mais disputados ao longo do tempo |

Implementação: nova route `/dashboard/coordination` + WebSocket events para coordination_log.

---

## O que NÃO muda

- API existente (`/tasks`, `/runs`, `/status`, webhooks) — 100% backward compatible
- Projetos sem `coordination.enabled: true` — zero impacto
- Dashboard existente — coordination é uma tab adicional, não substitui
- Worktree isolation — continua sendo a base, coordination adiciona awareness em cima
- Budget tracking — mediators contam no budget diário como qualquer outro run

---

## Critérios de aceite

1. Dois agentes executando tasks no mesmo repo detectam automaticamente quando ambos precisam do mesmo arquivo
2. Mediator agent spawna e faz ambas as mudanças coerentemente em um único commit
3. Branches dos agentes são rebaseados sobre a branch do mediator
4. PRs criados sem conflitos de merge
5. Se mediator falha, fallback para PRs separados com notificação
6. Dashboard mostra claims, mediations e timeline em tempo real
7. Testes cobrem: claim lifecycle, conflict detection, mediator spawning, rebase, fallback
8. `coordination.enabled: false` por padrão — zero breaking change
