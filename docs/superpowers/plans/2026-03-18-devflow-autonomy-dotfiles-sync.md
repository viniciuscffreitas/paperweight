# Dev Flow Autonomy + Dotfiles Sync — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar o Dev Flow mais autônomo (sem perguntas desnecessárias) e sincronizar o ambiente Mac ↔ Windows via dotfiles repo no Git.

**Architecture:** Dois chunks independentes — Chunk 1 edita `~/.claude/CLAUDE.md` para remover gates obrigatórios de spec; Chunk 2 cria um repo `~/dotfiles` com symlinks para `~/.claude/`, shell configs, e scripts de instalação por OS.

**Tech Stack:** Bash, zsh, PowerShell (install.ps1 mínimo), Git, WSL2 (Windows)

---

## Chunk 1: Autonomia no CLAUDE.md

**Files:**
- Modify: `~/.claude/CLAUDE.md:3-9` (seção "When to use /spec")

### Task 1: Substituir seção "When to use /spec"

- [ ] **Step 1: Ler o arquivo atual**

  Abrir `~/.claude/CLAUDE.md` e confirmar que as linhas 3–9 contêm:
  ```
  ### When to use /spec
  Use `/spec "description"` for any non-trivial task:
  - Features that add new behavior
  - Bugfixes (auto-detects -> Behavior Contract)
  - Refactoring with non-trivial scope

  Skip /spec only for trivial 1-2 line changes.
  ```

- [ ] **Step 2: Substituir a seção**

  Substituir as linhas 3–9 por:
  ```markdown
  ### When to use /spec
  Claude decides when `/spec` is needed: large features with multiple interdependent
  subsystems, changes to public contracts (APIs, schemas, database migrations), or
  refactors with high regression risk. For everything else, act directly without asking
  for approval. When in doubt, act and communicate the decision made.
  ```

- [ ] **Step 3: Adicionar seção "Autonomy" após "When to use /spec"**

  Inserir imediatamente após a seção editada (antes de `### TDD`):
  ```markdown

  ### Autonomy
  Act directly without asking for clarification or prior approval. Make technical
  choices based on code context. When there is ambiguity, pick the most reasonable
  interpretation and communicate the decision taken — do not ask first.
  ```

- [ ] **Step 4: Verificar o resultado**

  O arquivo deve ter esta sequência nas primeiras ~20 linhas:
  ```
  ## devflow v2.2 — Workflow & Quality

  ### When to use /spec
  Claude decides when `/spec` is needed: large features with multiple interdependent
  subsystems, changes to public contracts (APIs, schemas, database migrations), or
  refactors with high regression risk. For everything else, act directly without asking
  for approval. When in doubt, act and communicate the decision made.

  ### Autonomy
  Act directly without asking for clarification or prior approval. Make technical
  choices based on code context. When there is ambiguity, pick the most reasonable
  interpretation and communicate the decision taken — do not ask first.

  ### TDD
  ...
  ```

- [ ] **Step 5: Nota sobre commit**

  `~/.claude` ainda não é um repo Git — o commit do `CLAUDE.md` acontece automaticamente no **Task 3 Step 7** quando `~/.claude` for migrado para `~/dotfiles/claude/` e versionado. Não há ação aqui.

---

## Chunk 2: Dotfiles Repo

**Files:**
- Create: `~/dotfiles/.gitignore`
- Create: `~/dotfiles/install.sh`
- Create: `~/dotfiles/install.ps1`
- Create: `~/dotfiles/tools/install-tools.sh`
- Create: `~/dotfiles/shell/.aliases`
- Move: `~/.claude/` → `~/dotfiles/claude/` (com exclusões)
- Move: `~/.zshrc` → `~/dotfiles/shell/.zshrc`
- Move: `~/.bashrc` → `~/dotfiles/shell/.bashrc` (se existir)

### Task 2: Criar estrutura base do repo

- [ ] **Step 1: Criar diretório e inicializar Git**

  ```bash
  mkdir -p ~/dotfiles/claude ~/dotfiles/shell ~/dotfiles/tools
  cd ~/dotfiles
  git init
  ```

  Expected: `Initialized empty Git repository in ~/dotfiles/.git/`

- [ ] **Step 2: Criar .gitignore**

  Criar `~/dotfiles/.gitignore` com:
  ```gitignore
  # Gerado localmente por install.sh
  claude/settings.json

  # Dados sensíveis — nunca commitar
  claude/memory/
  claude/cache/
  claude/statsig/
  claude/sessions/
  claude/history.jsonl
  claude/*.log
  claude/hook-approvals.log
  claude/debug/
  claude/downloads/
  claude/paste-cache/
  claude/shell-snapshots/
  claude/stats-cache.json
  claude/telemetry/
  claude/todos/
  claude/tasks/
  claude/ide/
  claude/ccline/

  # Secrets
  **/.env
  **/.env.local
  **/*.key
  **/*.pem
  ```

- [ ] **Step 3: Commit inicial**

  ```bash
  cd ~/dotfiles
  git add .gitignore
  git commit -m "chore: init dotfiles repo"
  ```

### Task 3: Migrar ~/.claude/ para dotfiles

**Contexto importante:** `~/.claude/` contém vários diretórios que NÃO devem ir para o repo (cache, sessions, memory, etc.). A estratégia é: mover os arquivos/diretórios que queremos versionar para `~/dotfiles/claude/`, criar um symlink `~/.claude` → `~/dotfiles/claude/`, e deixar os diretórios excluídos sendo criados localmente pelo `install.sh`.

- [ ] **Step 1: Fazer backup antes de qualquer coisa**

  ```bash
  cp -r ~/.claude ~/.claude.backup.$(date +%Y%m%d)
  ```

  Expected: cria `~/.claude.backup.20260318` (ou data atual)

- [ ] **Step 2: Copiar arquivos versionáveis para dotfiles/claude/**

  ```bash
  # Arquivos raiz
  cp ~/.claude/CLAUDE.md ~/dotfiles/claude/

  # Devflow completo (sem __pycache__)
  cp -r ~/.claude/devflow ~/dotfiles/claude/
  find ~/dotfiles/claude/devflow -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true

  # Skills (symlinks do devflow — copiar os alvos)
  cp -r ~/.claude/skills ~/dotfiles/claude/

  # Plans e specs geradas
  mkdir -p ~/dotfiles/claude/plans
  cp -r ~/.claude/plans ~/dotfiles/claude/ 2>/dev/null; true

  # Plugins (apenas manifesto, não cache)
  mkdir -p ~/dotfiles/claude/plugins
  ls ~/.claude/plugins/  # inspecionar o que existe antes de copiar
  ```

  Após inspecionar: copiar apenas o que não é cache (ex: arquivos de configuração de plugins, não os binários baixados em `plugins/cache/`).

- [ ] **Step 3: Gerar settings.template.json**

  O `settings.json` contém caminhos absolutos como `/Users/vini/`. O padrão a substituir é o valor literal de `$HOME`:

  ```bash
  # Ver quantas ocorrências existem
  grep -c "$HOME" ~/.claude/settings.json
  # Expected: número > 0 (ex: 5, 10...)

  # Gerar o template (sed usa | como delimitador para evitar conflito com / nos paths)
  sed "s|$HOME|__HOME__|g" ~/.claude/settings.json > ~/dotfiles/claude/settings.template.json
  ```

  **Verificar que a substituição funcionou:**
  ```bash
  # Deve mostrar linhas com __HOME__
  grep "__HOME__" ~/dotfiles/claude/settings.template.json | head -5
  # Expected: linhas como "command": "__HOME__/.claude/devflow/hooks/..."

  # Não deve mais ter o path real
  grep -c "$HOME" ~/dotfiles/claude/settings.template.json
  # Expected: 0
  ```

  **Atenção:** O `settings.json` contém a Linear API key (`lin_api_...`). Ela vai permanecer no template. Se o repo for público, remover a key antes de commitar e usar variável de ambiente no futuro.

- [ ] **Step 4: Remover ~/.claude e criar symlink**

  **Verificar pré-condições antes de destruir o original:**
  ```bash
  # 1. Confirmar que o backup existe
  ls ~/.claude.backup.*/CLAUDE.md
  # Expected: mostra o arquivo — se falhar, PARE e investigue

  # 2. Confirmar que ~/dotfiles/claude tem conteúdo suficiente
  ls ~/dotfiles/claude/CLAUDE.md ~/dotfiles/claude/devflow/ ~/dotfiles/claude/settings.template.json
  # Expected: os três existem — se qualquer um faltar, PARE e volte ao Step 2/3
  ```

  **Somente após confirmar as pré-condições:**
  ```bash
  rm -rf ~/.claude
  ln -sf ~/dotfiles/claude ~/.claude
  ls -la ~ | grep .claude
  ```

  Expected: `lrwxr-xr-x ... .claude -> /Users/vini/dotfiles/claude`

- [ ] **Step 5: Recriar diretórios locais excluídos do repo**

  Esses diretórios existiam antes mas não estão no repo — precisam ser criados vazios:

  ```bash
  mkdir -p ~/.claude/memory
  mkdir -p ~/.claude/cache
  mkdir -p ~/.claude/sessions
  mkdir -p ~/.claude/statsig
  mkdir -p ~/.claude/downloads
  mkdir -p ~/.claude/paste-cache
  mkdir -p ~/.claude/debug
  mkdir -p ~/.claude/telemetry
  mkdir -p ~/.claude/todos
  mkdir -p ~/.claude/tasks
  mkdir -p ~/.claude/ide
  mkdir -p ~/.claude/ccline
  mkdir -p ~/.claude/plugins/cache
  ```

- [ ] **Step 6: Verificar que Claude Code ainda funciona**

  ```bash
  claude --version
  ```

  Expected: retorna versão sem erro.

  Se houver erro "settings.json not found", rodar:
  ```bash
  sed "s|__HOME__|$HOME|g" ~/dotfiles/claude/settings.template.json > ~/.claude/settings.json
  ```

- [ ] **Step 7: Commit**

  ```bash
  cd ~/dotfiles
  git add claude/
  git status  # verificar que memory/, cache/, etc. aparecem como untracked mas NÃO staged
  git commit -m "feat: migrar ~/.claude para dotfiles"
  ```

### Task 4: Migrar shell configs

> **Dependência:** Task 3 deve estar completa — `~/.claude` deve ser um symlink funcional antes de modificar o shell.

- [ ] **Step 1: Copiar .zshrc para dotfiles/shell/**

  ```bash
  cp ~/.zshrc ~/dotfiles/shell/.zshrc
  # Se tiver .bashrc:
  cp ~/.bashrc ~/dotfiles/shell/.bashrc 2>/dev/null; true
  ```

- [ ] **Step 2: Criar .aliases com aliases do dotfiles**

  Criar `~/dotfiles/shell/.aliases`:
  ```bash
  # Dotfiles sync
  alias dotpush='cd ~/dotfiles && git add -A && git commit -m "config: update $(date +%Y-%m-%d)" && git push'
  alias dotpull='cd ~/dotfiles && git pull'
  alias dotcd='cd ~/dotfiles'
  ```

- [ ] **Step 3: Adicionar source de .aliases no .zshrc**

  No final de `~/dotfiles/shell/.zshrc`, adicionar:
  ```bash
  # Dotfiles aliases
  [ -f ~/dotfiles/shell/.aliases ] && source ~/dotfiles/shell/.aliases
  ```

- [ ] **Step 4: Substituir .zshrc original por symlink**

  ```bash
  cp ~/.zshrc ~/.zshrc.backup.$(date +%Y%m%d)
  rm ~/.zshrc
  ln -sf ~/dotfiles/shell/.zshrc ~/.zshrc
  ls -la ~ | grep zshrc
  ```

  Expected: `lrwxr-xr-x ... .zshrc -> /Users/vini/dotfiles/shell/.zshrc`

- [ ] **Step 5: Testar shell**

  ```bash
  source ~/.zshrc
  dotpush --dry-run 2>/dev/null || echo "alias ok"
  type dotpush
  ```

  Expected: `dotpush is an alias for ...`

- [ ] **Step 6: Commit**

  ```bash
  cd ~/dotfiles
  git add shell/
  git commit -m "feat: migrar shell configs para dotfiles"
  ```

### Task 5: Escrever install.sh

- [ ] **Step 1: Criar ~/dotfiles/install.sh**

  ```bash
  #!/usr/bin/env bash
  set -e

  DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  echo "==> Dotfiles install: $DOTFILES_DIR"
  echo "==> HOME: $HOME"

  # Detectar OS
  OS="$(uname -s)"
  case "$OS" in
    Darwin) echo "==> OS: macOS" ;;
    Linux)  echo "==> OS: Linux/WSL2" ;;
    *)      echo "WARN: OS não reconhecido: $OS" ;;
  esac

  # --- Claude Code ---
  echo ""
  echo "--- Configurando ~/.claude ---"

  if [ -L "$HOME/.claude" ]; then
    echo "  symlink ~/.claude já existe, pulando"
  elif [ -d "$HOME/.claude" ]; then
    echo "  AVISO: ~/.claude é um diretório real. Fazendo backup..."
    mv "$HOME/.claude" "$HOME/.claude.backup.$(date +%Y%m%d%H%M%S)"
    ln -sf "$DOTFILES_DIR/claude" "$HOME/.claude"
    echo "  symlink criado: ~/.claude -> $DOTFILES_DIR/claude"
  else
    ln -sf "$DOTFILES_DIR/claude" "$HOME/.claude"
    echo "  symlink criado: ~/.claude -> $DOTFILES_DIR/claude"
  fi

  # Recriar diretórios locais excluídos do repo
  for dir in memory cache sessions statsig downloads paste-cache debug telemetry todos tasks ide ccline; do
    mkdir -p "$HOME/.claude/$dir"
  done
  mkdir -p "$HOME/.claude/plugins/cache"
  echo "  diretórios locais criados"

  # Gerar settings.json a partir do template
  if [ -f "$DOTFILES_DIR/claude/settings.template.json" ]; then
    sed "s|__HOME__|$HOME|g" "$DOTFILES_DIR/claude/settings.template.json" > "$HOME/.claude/settings.json"
    echo "  settings.json gerado para $HOME"
  else
    echo "  WARN: settings.template.json não encontrado"
  fi

  # --- Shell ---
  echo ""
  echo "--- Configurando shell ---"

  # .zshrc
  if [ -f "$HOME/.zshrc" ] && [ ! -L "$HOME/.zshrc" ]; then
    cp "$HOME/.zshrc" "$HOME/.zshrc.backup.$(date +%Y%m%d%H%M%S)"
  fi
  ln -sf "$DOTFILES_DIR/shell/.zshrc" "$HOME/.zshrc"
  echo "  symlink criado: ~/.zshrc"

  # .bashrc (opcional)
  if [ -f "$DOTFILES_DIR/shell/.bashrc" ]; then
    if [ -f "$HOME/.bashrc" ] && [ ! -L "$HOME/.bashrc" ]; then
      cp "$HOME/.bashrc" "$HOME/.bashrc.backup.$(date +%Y%m%d%H%M%S)"
    fi
    ln -sf "$DOTFILES_DIR/shell/.bashrc" "$HOME/.bashrc"
    echo "  symlink criado: ~/.bashrc"
  fi

  echo ""
  echo "==> Instalação concluída!"
  echo "    Execute 'source ~/.zshrc' para recarregar o shell."
  ```

- [ ] **Step 2: Tornar executável**

  ```bash
  chmod +x ~/dotfiles/install.sh
  ```

- [ ] **Step 3: Testar sintaxe e lógica básica**

  ```bash
  # Verificar sintaxe bash (não executa, só analisa)
  bash -n ~/dotfiles/install.sh && echo "sintaxe ok"
  # Expected: "sintaxe ok"

  # Verificar que o script detecta o OS corretamente (execução real, sem modificar arquivos)
  # O script usa set -e mas a lógica de symlink verifica existência antes de agir
  # Rodar com DOTFILES_DIR apontando para local seguro para testar apenas o echo de OS:
  bash -c 'OS="$(uname -s)"; case "$OS" in Darwin) echo "macOS detectado ok";; Linux) echo "Linux detectado ok";; esac'
  # Expected: "macOS detectado ok" (no Mac)
  ```

- [ ] **Step 4: Commit**

  ```bash
  cd ~/dotfiles
  git add install.sh
  git commit -m "feat: install.sh para macOS e WSL2"
  ```

### Task 6: Escrever install.ps1 (Windows bootstrap)

- [ ] **Step 1: Criar ~/dotfiles/install.ps1**

  ```powershell
  # install.ps1 — Bootstrap Windows para usar dotfiles via WSL2
  # Executa no PowerShell como Administrador

  Write-Host "==> Dotfiles Bootstrap (Windows)" -ForegroundColor Cyan

  # Instalar WSL2 com Ubuntu
  Write-Host ""
  Write-Host "--- Instalando WSL2 ---"
  wsl --install -d Ubuntu

  Write-Host ""
  Write-Host "--- Instalando ferramentas nativas ---"

  # Verificar se winget está disponível
  if (Get-Command winget -ErrorAction SilentlyContinue) {
      winget install -e --id Git.Git
      winget install -e --id Microsoft.WindowsTerminal
      winget install -e --id Microsoft.VisualStudioCode
      Write-Host "  Ferramentas instaladas via winget"
  } else {
      Write-Host "  WARN: winget nao encontrado. Instale manualmente:"
      Write-Host "    - Git for Windows: https://git-scm.com/download/win"
      Write-Host "    - Windows Terminal: Microsoft Store"
  }

  Write-Host ""
  Write-Host "==> Proximo passo:" -ForegroundColor Green
  Write-Host "    1. Reinicie o Windows para completar a instalacao do WSL2"
  Write-Host "    2. Abra o Ubuntu no Windows Terminal"
  Write-Host "    3. Execute dentro do WSL2:"
  Write-Host "       git clone https://github.com/SEU_USER/dotfiles ~/dotfiles"
  Write-Host "       bash ~/dotfiles/install.sh"
  Write-Host "       source ~/.zshrc"
  ```

- [ ] **Step 2: Commit**

  ```bash
  cd ~/dotfiles
  git add install.ps1
  git commit -m "feat: install.ps1 bootstrap Windows/WSL2"
  ```

### Task 7: Escrever tools/install-tools.sh

- [ ] **Step 1: Criar ~/dotfiles/tools/install-tools.sh**

  ```bash
  #!/usr/bin/env bash
  # Instala ferramentas de desenvolvimento por OS
  set -e

  OS="$(uname -s)"

  install_mac() {
    echo "==> Instalando ferramentas macOS via Homebrew"

    # Instalar Homebrew se não existir
    if ! command -v brew &>/dev/null; then
      echo "  Instalando Homebrew..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi

    brew install git node python3 gh
    brew install --cask visual-studio-code

    echo "  macOS tools instaladas"
  }

  install_linux() {
    echo "==> Instalando ferramentas Linux/WSL2 via apt"
    sudo apt-get update -qq
    sudo apt-get install -y git curl wget unzip build-essential python3 python3-pip nodejs npm

    # GitHub CLI
    if ! command -v gh &>/dev/null; then
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
      sudo apt update && sudo apt install gh -y
    fi

    echo "  Linux/WSL2 tools instaladas"
  }

  case "$OS" in
    Darwin) install_mac ;;
    Linux)  install_linux ;;
    *)      echo "OS não suportado: $OS"; exit 1 ;;
  esac

  echo ""
  echo "==> Ferramentas instaladas com sucesso!"
  ```

- [ ] **Step 2: Tornar executável e commitar**

  ```bash
  chmod +x ~/dotfiles/tools/install-tools.sh
  cd ~/dotfiles
  git add tools/
  git commit -m "feat: install-tools.sh para macOS e Linux/WSL2"
  ```

### Task 8: Push para GitHub e verificação final

- [ ] **Step 1: Criar repo privado no GitHub**

  ```bash
  cd ~/dotfiles
  # Verificar se remote já existe antes de criar
  git remote -v
  # Se "origin" aparecer, o remote já foi criado — pular gh repo create e fazer apenas git push -u origin main
  ```

  Se **não** houver remote:
  ```bash
  gh repo create dotfiles --private --source=. --remote=origin --push
  ```

  Expected:
  ```
  ✓ Created repository vini-coelho/dotfiles on GitHub
  ✓ Added remote https://github.com/vini-coelho/dotfiles.git
  ✓ Pushed commits to https://github.com/vini-coelho/dotfiles.git
  ```

  Se já houver remote (re-execução):
  ```bash
  git push -u origin main
  ```

- [ ] **Step 2: Verificar estrutura completa do repo**

  ```bash
  cd ~/dotfiles
  git log --oneline
  ls -la
  ls -la claude/
  ls -la shell/
  ```

  Expected: ver commits das tasks anteriores e estrutura correta de diretórios.

- [ ] **Step 3: Verificar que memory/ e cache/ NÃO estão no repo**

  ```bash
  cd ~/dotfiles
  git ls-files | grep memory  # deve retornar vazio
  git ls-files | grep cache   # deve retornar vazio
  git ls-files | grep settings.json  # deve retornar vazio (só o template)
  ```

  Expected: sem output para os três comandos.

- [ ] **Step 4: Verificar que settings.json local está correto**

  ```bash
  grep -c "__HOME__" ~/.claude/settings.json  # deve ser 0 — placeholder já foi substituído
  grep "/Users/vini\|/home/" ~/.claude/settings.json | head -3  # deve ver o home real
  ```

- [ ] **Step 5: Testar aliases de sync**

  ```bash
  source ~/.zshrc
  type dotpush
  type dotpull
  ```

  Expected:
  ```
  dotpush is an alias for cd ~/dotfiles && git add -A && ...
  dotpull is an alias for cd ~/dotfiles && git pull
  ```

- [ ] **Step 6: Verificar que Claude Code ainda funciona**

  ```bash
  claude --version
  ls ~/.claude/  # ver symlink funcionando
  ```

---

## Critérios de Aceite Finais

### Chunk 1 — Autonomia
- [ ] `~/.claude/CLAUDE.md` contém seção "Autonomy" após "When to use /spec"
- [ ] Nova sessão do Claude Code: pedir tarefa simples → Claude age sem perguntar
- [ ] Nova sessão do Claude Code: pedir tarefa ambígua → Claude escolhe e comunica

### Chunk 2 — Dotfiles
- [ ] `~/.claude` é um symlink apontando para `~/dotfiles/claude`
- [ ] `~/.claude/memory/` existe localmente e não está no repo (`git ls-files | grep memory` retorna vazio)
- [ ] `~/.claude/settings.json` contém o `$HOME` real (não `__HOME__`)
- [ ] `~/dotfiles` tem remote no GitHub e push feito com sucesso
- [ ] `dotpush` e `dotpull` funcionam no terminal
- [ ] No Windows: clonar `~/dotfiles` dentro do WSL2, rodar `install.sh`, verificar `~/.claude` symlink

---

## Instruções para Setup no Windows (pós-plano)

Após o Mac estar configurado e o repo no GitHub:

1. No Windows, abrir PowerShell como Administrador
2. Rodar `install.ps1` (baixar do GitHub ou copiar)
3. Reiniciar o Windows
4. Abrir Ubuntu no Windows Terminal
5. Dentro do WSL2:
   ```bash
   git clone https://github.com/SEU_USER/dotfiles ~/dotfiles
   bash ~/dotfiles/tools/install-tools.sh
   bash ~/dotfiles/install.sh
   source ~/.zshrc
   ```
6. Instalar Claude Code no WSL2:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
7. Verificar: `claude --version` e `ls -la ~/.claude`
