# Design: Dev Flow Autonomy + Dotfiles Sync

**Data:** 2026-03-18
**Status:** Aprovado

---

## Problema

O Dev Flow atual é percebido como burocrático em dois eixos:

1. **Processo de spec/brainstorming obrigatório** — mesmo tarefas simples passam por 9 etapas (clarifying questions, design doc, spec review loop, user review), gerando overhead desproporcional ao risco.
2. **Confirmações durante execução** — Claude faz perguntas de clarificação e espera aprovação antes de agir, interrompendo o ritmo de trabalho.

Adicionalmente, o usuário trabalha em Mac e Windows e precisa que ambos os sistemas estejam sincronizados com o mesmo ambiente (código, configuração do Claude Code, ferramentas).

---

## Solução 1 — Autonomia no Dev Flow

### Mudanças no `~/.claude/CLAUDE.md`

**Seção "When to use /spec" — nova versão:**

> Claude decide quando `/spec` é necessário: features grandes com múltiplos subsistemas interdependentes, mudanças em contratos públicos (APIs, schemas), ou refactors com alto risco de regressão. Para todo o resto, agir diretamente sem pedir aprovação.

**Nova seção "Autonomy":**

> Age diretamente sem pedir clarificação ou aprovação prévia. Faz escolhas técnicas com base no contexto do código. Se houver ambiguidade, escolhe a interpretação mais razoável e comunica a decisão tomada — não pergunta antes.

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
- Review gate para PRs não-triviais

---

## Solução 2 — Dotfiles Repo (Mac ↔ Windows Sync)

### Estrutura do repositório

```
~/dotfiles/
├── install.sh           # macOS e Linux/WSL — detecta OS, cria symlinks
├── install.ps1          # Windows nativo (opcional, WSL preferível)
├── claude/
│   ├── CLAUDE.md
│   ├── settings.json    # com placeholders para caminhos por OS
│   ├── devflow/
│   └── memory/
├── shell/
│   ├── .zshrc
│   ├── .bashrc
│   └── .aliases
└── tools/
    └── install-tools.sh  # brew (mac) / apt (WSL)
```

### Estratégia Windows

Recomenda-se WSL2 (Ubuntu) em vez de Windows nativo:
- `install.sh` funciona igual ao Mac
- Ferramentas CLI idênticas (git, python, node)
- Sem necessidade de adaptar scripts para PowerShell

### Caminhos absolutos no settings.json

O `settings.json` contém caminhos como `/Users/vini/` (Mac) vs `/home/vini/` (WSL).
O `install.sh` aplica substituição via `sed` no momento do symlink, gerando o arquivo correto por ambiente.

### Workflow de sync

```
# Após qualquer mudança de config:
cd ~/dotfiles && git add -A && git commit -m "config: <descrição>" && git push

# No outro sistema:
cd ~/dotfiles && git pull
# symlinks já apontam para os arquivos atualizados
```

### Conteúdo excluído do repo

- Tokens e API keys do `settings.json` — usar variáveis de ambiente ou arquivo `.env.local` ignorado pelo `.gitignore`
- Caches (`~/.claude/cache/`, `~/.claude/statsig/`)
- Logs e histórico de sessões

---

## Plano de implementação

### Fase 1 — Autonomia (CLAUDE.md)
1. Editar `~/.claude/CLAUDE.md`: substituir seção "When to use /spec" + adicionar seção "Autonomy"
2. Testar comportamento em conversa simples

### Fase 2 — Dotfiles repo
1. Criar `~/dotfiles` como repo Git privado
2. Mover `~/.claude/` para `~/dotfiles/claude/` e criar symlink
3. Adicionar configs de shell
4. Escrever `install.sh` com detecção de OS e substituição de caminhos
5. Push para GitHub
6. Configurar WSL2 no Windows e executar `install.sh`
