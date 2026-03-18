# Design: Dev Flow Autonomy + Dotfiles Sync

**Data:** 2026-03-18
**Status:** Em revisão

---

## Problema

O Dev Flow atual é percebido como burocrático em dois eixos:

1. **Processo de spec/brainstorming obrigatório** — mesmo tarefas simples passam por 9 etapas (clarifying questions, design doc, spec review loop, user review), gerando overhead desproporcional ao risco.
2. **Confirmações durante execução** — Claude faz perguntas de clarificação e espera aprovação antes de agir, interrompendo o ritmo de trabalho.

Adicionalmente, o usuário trabalha em Mac e Windows e precisa que ambos os sistemas estejam sincronizados com o mesmo ambiente (código, configuração do Claude Code, ferramentas de desenvolvimento).

---

## Solução 1 — Autonomia no Dev Flow

### Mudanças no `~/.claude/CLAUDE.md`

**Seção "When to use /spec" — substituir por:**
```
### When to use /spec
Claude decides when `/spec` is needed: large features with multiple interdependent
subsystems, changes to public contracts (APIs, schemas, database migrations), or
refactors with high regression risk. For everything else, act directly without asking
for approval. When in doubt, act and communicate the decision made.
```

**Nova seção "Autonomy" — adicionar após "When to use /spec":**
```
### Autonomy
Act directly without asking for clarification or prior approval. Make technical
choices based on code context. When there is ambiguity, pick the most reasonable
interpretation and communicate the decision taken — do not ask first.
```

### Comportamento resultante

| Antes | Depois |
|-------|--------|
| `/spec` obrigatório para tarefas não-triviais | Claude julga quando spec é necessário |
| Brainstorming com 9 etapas disparado automaticamente | Spec só via `/spec` explícito |
| Claude para para perguntar "posso prosseguir?" | Age direto, comunica decisões depois |
| TDD como gate de aprovação | TDD como guia de qualidade |

### O que NÃO muda

- Verificação final (lint, build, testes) antes de declarar "done"
- `/spec` continua disponível quando o usuário quiser o processo formal
- TDD continua sendo a abordagem preferida para implementação
- Review gate via `pr-review-toolkit:review-pr` para PRs não-triviais

### Critério de aceite — Solução 1

- Em uma nova sessão, pedir ao Claude uma tarefa de implementação simples (ex: "adiciona um campo novo no modelo X") → Claude começa a implementar sem perguntar nada
- Pedir uma tarefa ambígua (ex: "melhora a performance do dashboard") → Claude escolhe uma abordagem e comunica, sem esperar resposta

---

## Solução 2 — Dotfiles Repo (Mac ↔ Windows Sync)

### Decisão sobre Windows

**WSL2 (Ubuntu) é a abordagem principal.** O `install.sh` funciona igual no Mac e WSL2. O `install.ps1` existe para configurar o WSL2 no Windows e instalar ferramentas nativas necessárias (Git for Windows, terminal), mas não gerencia dotfiles diretamente — isso fica no WSL2.

### Estrutura do repositório

```
~/dotfiles/
├── .gitignore
├── install.sh              # macOS e WSL2/Linux
├── install.ps1             # Windows: instala WSL2 + ferramentas nativas
├── claude/
│   ├── CLAUDE.md
│   ├── settings.template.json   # settings com placeholder __HOME__
│   ├── devflow/
│   └── memory/             # EXCLUÍDO do git (ver .gitignore)
├── shell/
│   ├── .zshrc              # macOS (zsh)
│   ├── .bashrc             # WSL2 (bash/zsh)
│   └── .aliases            # aliases compartilhados, sourced em ambos
└── tools/
    └── install-tools.sh    # brew (mac) / apt (WSL2)
```

### Tratamento de `memory/`

`~/.claude/memory/` contém dados sensíveis (IPs de VPS, paths, contexto de sessão) e **não entra no dotfiles repo**. O `.gitignore` exclui explicitamente `claude/memory/`. Na instalação em uma nova máquina, o diretório é criado vazio.

### Caminhos absolutos no `settings.json`

O `settings.json` contém caminhos como `/Users/vini/` que diferem por OS. Solução:
- O repo armazena `settings.template.json` com o placeholder `__HOME__`
- O `install.sh` gera `settings.json` real via:
  ```bash
  sed "s|__HOME__|$HOME|g" claude/settings.template.json > ~/.claude/settings.json
  ```
- O `settings.json` gerado é symlink-less (arquivo copiado), nunca commited

### `.gitignore` do dotfiles repo

```gitignore
# Gerado localmente
claude/settings.json

# Dados sensíveis
claude/memory/
claude/cache/
claude/statsig/
claude/sessions/
claude/history.jsonl
claude/*.log

# Secrets
**/.env
**/*.key
```

### Workflow de sync

```bash
# Após qualquer mudança de config em qualquer máquina:
cd ~/dotfiles
git add -A
git commit -m "config: <descrição da mudança>"
git push

# No outro sistema, para receber as mudanças:
cd ~/dotfiles
git pull
# O install.sh NÃO precisa rodar de novo — symlinks já apontam para os arquivos atualizados
# Exceção: se novos arquivos foram adicionados ao repo, rodar install.sh novamente
```

**Conflitos:** O dotfiles é de uso single-author — conflitos são raros. Se ocorrer, resolver manualmente como qualquer conflito Git. Não há automação de merge.

**Alias sugerido** (vai no `.aliases`):
```bash
alias dotpush='cd ~/dotfiles && git add -A && git commit -m "config: update" && git push'
alias dotpull='cd ~/dotfiles && git pull'
```

---

## Plano de implementação

### Fase 1 — Autonomia no CLAUDE.md

1. Abrir `~/.claude/CLAUDE.md`
2. Localizar a seção `### When to use /spec` e substituir pelo texto especificado acima
3. Adicionar a seção `### Autonomy` imediatamente após
4. Salvar e iniciar nova sessão do Claude Code
5. **Validar critério de aceite:** pedir tarefa simples → Claude age direto; pedir tarefa ambígua → Claude escolhe e comunica

### Fase 2 — Dotfiles repo

1. Criar `~/dotfiles` e inicializar como repo Git
2. Criar repo privado no GitHub (ex: `vini/dotfiles`)
3. Mover `~/.claude/` para `~/dotfiles/claude/` (exceto `memory/`, `cache/`, `sessions/`, `history.jsonl`)
4. Criar `~/dotfiles/claude/.gitignore` com as exclusões listadas
5. Gerar `settings.template.json` a partir do `settings.json` atual (substituir `$HOME` real por `__HOME__`)
6. Criar symlink: `ln -sf ~/dotfiles/claude ~/.claude`
7. Mover configs de shell (`.zshrc`, `.bashrc`) para `~/dotfiles/shell/` e criar symlinks
8. Escrever `install.sh`:
   - Detectar OS (`uname`)
   - Criar symlinks para cada arquivo/diretório
   - Rodar `sed` para gerar `settings.json` a partir do template
   - Criar `~/.claude/memory/` vazio se não existir
9. Escrever `install.ps1`:
   - Instalar WSL2 via `wsl --install`
   - Instalar Git for Windows, Windows Terminal
   - Instruções para clonar dotfiles dentro do WSL2
10. Escrever `tools/install-tools.sh` (brew / apt por OS)
11. Push para GitHub
12. No Windows: rodar `install.ps1`, depois dentro do WSL2 clonar o repo e rodar `install.sh`

### Critério de aceite — Fase 2

- `~/.claude/CLAUDE.md` no Mac e no Windows (WSL2) são o mesmo arquivo via symlink do dotfiles
- Mudança feita no Mac → push → pull no Windows → arquivo atualizado automaticamente
- `memory/` existe localmente em cada máquina mas não está no repo
- `settings.json` gerado corretamente com o `$HOME` de cada OS
