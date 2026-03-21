// ── Task Detail: activity feed, tab switching, task lifecycle ──
// Chat functions live in chat.js (loaded before this file).

var _taskConfig = {};
var _taskWs = null;

// ── Multimodal state (used by chat.js) ──
var _chatAttachments = []; // [{dataUrl, path, filename}] — path set after upload
var _voiceRecognition = null;
var _voiceActive = false;

function initTaskDetail(config) {
  _taskConfig = config;

  // Model selector: switch model mid-session (backend updates session.model)
  var modelSelect = document.getElementById('chat-model');
  if (modelSelect) {
    if (config.currentModel) modelSelect.value = config.currentModel;
    modelSelect.addEventListener('change', function() {
      var chatMessages = document.getElementById('chat-messages');
      if (chatMessages) {
        var note = document.createElement('div');
        note.style.cssText = 'text-align:center;font-size:11px;color:var(--text-disabled);padding:8px 0;';
        note.textContent = 'Next message will use ' + modelSelect.options[modelSelect.selectedIndex].text;
        chatMessages.appendChild(note);
      }
    });
  }

  setupTabSwitching();
  initMultimodal();

  if (config.sessionId) {
    loadActivityFeed(config.sessionId);
  } else if (config.status === 'running' || config.status === 'pending') {
    showEmptyActivity('Waiting for agent to start...');
  } else {
    showEmptyActivity('No activity recorded');
  }

  // Auto-start brainstorming for draft tasks without a session
  if (config.status === 'draft' && !config.sessionId) {
    autoBrainstorm();
  }
}

// ── Tab switching ──

function setupTabSwitching() {
  var container = document.querySelector('[style*="border-bottom:1px solid var(--separator-strong)"]');
  if (!container) return;
  var buttons = container.querySelectorAll('button');
  var tabs = [];
  buttons.forEach(function(btn) {
    tabs.push(btn.textContent.trim().toLowerCase());
  });

  buttons.forEach(function(btn, i) {
    btn.removeAttribute('hx-get');
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      switchTab(tabs[i] || 'activity', btn, buttons);
    });
  });
}

function switchTab(tabName, activeBtn, allButtons) {
  allButtons.forEach(function(btn) {
    btn.style.color = 'var(--text-muted)';
    btn.style.borderBottom = '2px solid transparent';
    delete btn.dataset.active;
  });
  activeBtn.style.color = 'var(--text-primary)';
  activeBtn.style.borderBottom = '2px solid var(--accent-text)';
  activeBtn.dataset.active = 'true';

  var spec = document.getElementById('spec-content');
  var activity = document.getElementById('activity-feed');
  var output = document.getElementById('output-content');
  var chat = document.getElementById('chat-content');

  if (spec) spec.style.display = tabName === 'spec' ? 'block' : 'none';
  if (activity) activity.style.display = tabName === 'activity' ? 'block' : 'none';
  if (output) output.style.display = tabName === 'output' ? 'block' : 'none';
  if (chat) chat.style.display = tabName === 'chat' ? 'flex' : 'none';

  if (tabName === 'chat') {
    var input = document.getElementById('chat-input');
    if (input) input.focus();
  }
}

// ── Activity feed ──

function loadActivityFeed(sessionId) {
  fetch('/api/sessions/' + sessionId + '/events')
    .then(function(r) { return r.json(); })
    .then(function(events) {
      var container = document.getElementById('activity-events');
      if (!container) return;

      var lastOutput = '';
      events.forEach(function(ev) {
        if (ev.type === 'tool_use') {
          var actLabel = parseToolLabel(ev);
          renderActivityEvent(container, ev.tool_name || 'Tool', actLabel, '');
        } else if (ev.type === 'assistant' && ev.content) {
          lastOutput += ev.content + '\n';
        } else if (ev.type === 'tool_result' && ev.content) {
          var items = container.children;
          if (items.length > 0) {
            var lastItem = items[items.length - 1];
            var detail = lastItem.querySelector('[style*="text-disabled"]');
            if (detail) detail.textContent = ev.content.substring(0, 100);
          }
        }
      });

      var outputText = document.getElementById('output-text');
      if (outputText && lastOutput) {
        if (typeof marked !== 'undefined') {
          outputText.innerHTML = marked.parse(lastOutput.trim());
          outputText.classList.add('chat-msg-content');
          addCodeBlockHeaders(outputText);
          if (typeof hljs !== 'undefined') {
            outputText.querySelectorAll('pre code').forEach(function(block) {
              hljs.highlightElement(block);
            });
          }
        } else {
          outputText.textContent = lastOutput.trim();
        }
      }

      if (_taskConfig.status === 'running') {
        connectTaskStream();
      }

      loadChatHistory(events);
    })
    .catch(function() {
      showEmptyActivity('Failed to load activity');
    });
}

function connectTaskStream() {
  fetch('/api/sessions/' + _taskConfig.sessionId + '/events')
    .then(function(r) { return r.json(); })
    .then(function() {
      showThinking();
    });
}

function parseToolLabel(ev) {
  if (ev.file_path) return ev.file_path;
  var content = ev.content || '';
  try {
    var parsed = JSON.parse(content);
    if (parsed.skill) return parsed.skill + (parsed.args ? ' ' + parsed.args.substring(0, 40) : '');
    if (parsed.description) return parsed.description;
    if (parsed.command) {
      var cmd = parsed.command;
      if (cmd.length > 60) cmd = cmd.substring(0, 57) + '...';
      return cmd;
    }
    if (parsed.file_path) return parsed.file_path;
    if (parsed.pattern) return (parsed.glob || '') + ' ' + parsed.pattern;
    if (parsed.query) return parsed.query;
    if (parsed.prompt) return parsed.prompt.substring(0, 60);
  } catch (e) { /* not JSON */ }
  if (content.length > 80) return content.substring(0, 77) + '...';
  return content;
}

function renderActivityEvent(container, toolName, label, timestamp) {
  var colorMap = {
    'Edit': '#22c55e', 'Write': '#22c55e',
    'Bash': '#fbbf24',
    'Read': '#818cf8', 'Grep': '#818cf8', 'Glob': '#818cf8'
  };
  var color = colorMap[toolName] || '#c084fc';

  var row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:flex-start;gap:8px;padding:6px 0;font-size:12px;';

  var bar = document.createElement('div');
  bar.style.cssText = 'width:2px;min-height:20px;background:' + color + ';border-radius:1px;flex-shrink:0;margin-top:2px;';

  var content = document.createElement('div');
  content.style.cssText = 'flex:1;min-width:0;';

  var header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;gap:6px;';

  var nameSpan = document.createElement('span');
  nameSpan.style.cssText = 'font-weight:600;color:' + color + ';';
  nameSpan.textContent = toolName;

  var labelSpan = document.createElement('span');
  labelSpan.style.cssText = 'color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  labelSpan.textContent = label ? label.substring(0, 80) : '';

  header.appendChild(nameSpan);
  header.appendChild(labelSpan);
  content.appendChild(header);

  row.appendChild(bar);
  row.appendChild(content);

  if (timestamp) {
    var timeSpan = document.createElement('span');
    timeSpan.style.cssText = 'font-size:10px;color:var(--text-disabled);flex-shrink:0;';
    timeSpan.textContent = timestamp;
    row.appendChild(timeSpan);
  }

  container.appendChild(row);
}

function showEmptyActivity(message) {
  var container = document.getElementById('activity-events');
  if (container) {
    container.innerHTML = '<div style="padding:24px 0;text-align:center;color:var(--text-disabled);font-size:13px;">' + message + '</div>';
  }
}

// ── Task lifecycle ──

function cancelRun() {
  var btn = document.querySelector('[onclick="cancelRun()"]');
  if (btn) { btn.textContent = 'Cancelling...'; btn.style.opacity = '0.6'; btn.disabled = true; }

  var promises = [];
  if (_taskConfig.runId) {
    promises.push(
      fetch('/runs/' + _taskConfig.runId + '/cancel', { method: 'POST' }).catch(function() {})
    );
  }
  if (_taskConfig.sessionId) {
    promises.push(
      fetch('/api/sessions/' + _taskConfig.sessionId + '/close', { method: 'POST' }).catch(function() {})
    );
  }
  promises.push(
    fetch('/api/work-items/' + _taskConfig.taskId, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ status: 'pending' })
    }).catch(function() {})
  );
  if (_taskWs) { _taskWs.close(); _taskWs = null; }

  Promise.all(promises).then(function() {
    window.location.reload();
  });
}

function startTask() {
  var btn = document.querySelector('[onclick="startTask()"]');
  if (btn) { btn.textContent = 'Starting...'; btn.style.opacity = '0.6'; btn.disabled = true; }

  var desc = document.getElementById('task-description');
  var titleEl = document.querySelector('[style*="font-size:20px"]');
  var taskTitle = titleEl ? titleEl.textContent.trim() : '';

  var specEl = document.getElementById('spec-content');
  var specPath = specEl ? specEl.getAttribute('data-spec-path') : '';
  var prompt = '';
  if (specPath) {
    prompt = 'Implement the spec at ' + specPath + '. Read the file first, then implement fully: RED tests → GREEN implementation → REFACTOR → COMMIT. Run tests and linter before finishing.';
  } else {
    // No spec found in template — tell agent to search for it
    var specHint = 'Look for the spec in docs/superpowers/specs/ (file matching "' + taskTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').substring(0, 40) + '"). ';
    var taskDesc = desc ? desc.textContent.trim() : taskTitle;
    prompt = specHint + 'If found, implement it. If not, implement based on this description:\n\n' + taskDesc;
  }

  var modelSelect = document.getElementById('chat-model');
  var model = modelSelect ? modelSelect.value : 'claude-sonnet-4-6';

  fetch('/api/projects/' + _taskConfig.projectId + '/agent', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ prompt: prompt, model: model, max_cost_usd: 2.0 })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    _taskConfig.sessionId = data.session_id;
    _taskConfig.runId = data.run_id;
    _taskConfig.status = 'running';

    fetch('/api/work-items/' + _taskConfig.taskId, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ session_id: data.session_id, status: 'running' })
    });

    var statusBadge = document.querySelector('[style*="text-transform:uppercase"]');
    if (statusBadge) { statusBadge.textContent = 'running'; statusBadge.style.color = 'var(--status-running)'; }

    if (btn) {
      btn.textContent = 'Cancel';
      btn.style.opacity = '1';
      btn.disabled = false;
      btn.style.background = 'transparent';
      btn.style.color = 'var(--status-error)';
      btn.style.border = '1px solid var(--status-error)';
      btn.setAttribute('onclick', 'cancelRun()');
    }

    var activityFeed = document.getElementById('activity-feed');
    var specTab = document.getElementById('spec-content');
    if (specTab) specTab.style.display = 'none';
    if (activityFeed) activityFeed.style.display = 'block';
    var eventsContainer = document.getElementById('activity-events');
    if (eventsContainer) eventsContainer.innerHTML = '';

    var tabButtons = document.querySelectorAll('[style*="border-bottom:1px solid var(--separator-strong)"] button');
    tabButtons.forEach(function(b) {
      var isActivity = b.textContent.trim().toLowerCase() === 'activity';
      b.style.color = isActivity ? 'var(--text-primary)' : 'var(--text-muted)';
      b.style.borderBottom = isActivity ? '2px solid var(--accent-text)' : '2px solid transparent';
    });

    showThinking();
    _taskWs = connectRunStream(data.run_id,
      function(event) {
        hideThinking();
        if (event.type === 'tool_use') {
          renderActivityEvent(eventsContainer, event.tool_name || 'Tool', parseToolLabel(event), '');
          eventsContainer.parentElement.scrollTop = eventsContainer.parentElement.scrollHeight;
        } else if (event.type === 'assistant' && event.content) {
          var outputText = document.getElementById('output-text');
          if (outputText) {
            outputText.textContent += event.content;
          }
        }
      },
      function() {
        hideThinking();
        if (btn) { btn.textContent = 'Rerun'; btn.setAttribute('onclick', 'rerunTask()'); }
        var done = document.createElement('div');
        done.style.cssText = 'padding:16px 0;text-align:center;color:var(--status-success);font-size:13px;';
        done.textContent = 'Task completed — reloading...';
        setTimeout(function() { window.location.reload(); }, 2000);
        eventsContainer.appendChild(done);
      },
      function() {
        hideThinking();
        if (btn) { btn.textContent = 'Rerun'; btn.setAttribute('onclick', 'rerunTask()'); }
      }
    );
  })
  .catch(function(err) {
    if (btn) { btn.textContent = 'Start'; btn.style.opacity = '1'; btn.disabled = false; }
    var eventsContainer = document.getElementById('activity-events');
    if (eventsContainer) {
      var errDiv = document.createElement('div');
      errDiv.style.cssText = 'padding:16px 0;text-align:center;color:var(--status-error);font-size:13px;';
      errDiv.textContent = 'Failed to start: ' + err.message;
      eventsContainer.appendChild(errDiv);
    }
  });
}

function rerunTask() {
  fetch('/api/work-items/' + _taskConfig.taskId + '/rerun', { method: 'POST' })
    .then(function() {
      startTask();
    });
}

function autoBrainstorm() {
  var titleEl = document.querySelector('[style*="font-size:20px"]');
  var title = titleEl ? titleEl.textContent.trim() : '';

  var prompt = 'BRAINSTORMING MODE — You are brainstorming, NOT implementing.\n\n' +
    'The user\'s idea: "' + title + '"\n\n' +
    'RULES:\n' +
    '- NEVER write code, create files, or edit source files\n' +
    '- NEVER skip to implementation\n' +
    '- ONLY brainstorm, ask questions, and produce a spec document\n\n' +
    'WORKFLOW:\n' +
    '1. Read CLAUDE.md (it has detailed brainstorming instructions)\n' +
    '2. Explore the codebase to understand context\n' +
    '3. Ask the user clarifying questions ONE AT A TIME\n' +
    '4. Propose 2-3 approaches with trade-offs\n' +
    '5. Present the design for approval\n' +
    '6. When approved, write spec to docs/superpowers/specs/\n' +
    '7. PATCH task to ready: curl -s -X PATCH http://localhost:8080/api/work-items/' + _taskConfig.taskId + ' -H "Content-Type: application/json" -d \'{"status": "ready"}\'\n' +
    '8. Update title: curl -s -X PATCH http://localhost:8080/api/work-items/' + _taskConfig.taskId + ' -H "Content-Type: application/json" -d \'{"title": "Better Title"}\'\n\n' +
    'STOP after writing the spec. The user will click Start to trigger implementation.';

  var modelSelect = document.getElementById('chat-model');
  var model = modelSelect ? modelSelect.value : 'claude-sonnet-4-6';

  // Switch to chat tab
  var chatTab = document.getElementById('chat-content');
  var specTab = document.getElementById('spec-content');
  var activityFeed = document.getElementById('activity-feed');
  if (chatTab) chatTab.style.display = 'flex';
  if (specTab) specTab.style.display = 'none';
  if (activityFeed) activityFeed.style.display = 'none';

  // Activate chat tab button
  var tabButtons = document.querySelectorAll('[style*="border-bottom:1px solid var(--separator-strong)"] button');
  tabButtons.forEach(function(b) {
    var isChat = b.textContent.trim().toLowerCase() === 'chat';
    b.style.color = isChat ? 'var(--text-primary)' : 'var(--text-muted)';
    b.style.borderBottom = isChat ? '2px solid var(--accent-text)' : '2px solid transparent';
  });

  showThinking();

  fetch('/api/projects/' + _taskConfig.projectId + '/agent', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ prompt: prompt, model: model, max_cost_usd: 2.0 })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    _taskConfig.sessionId = data.session_id;
    _taskConfig.runId = data.run_id;

    // Link session to task
    fetch('/api/work-items/' + _taskConfig.taskId, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ session_id: data.session_id })
    });

    // Connect WebSocket for streaming
    var chatMessages = document.getElementById('chat-messages');
    hideThinking();

    var streamingContent = null;
    var streamingText = '';
    var typewriterQueue = [];
    var typewriterRunning = false;
    var renderTimer = null;

    function typewriterTick() {
      if (typewriterQueue.length === 0) { typewriterRunning = false; return; }
      typewriterRunning = true;
      var batch = Math.min(3, typewriterQueue.length);
      for (var i = 0; i < batch; i++) { streamingText += typewriterQueue.shift(); }
      streamingContent.textContent = streamingText;
      chatMessages.scrollTop = chatMessages.scrollHeight;
      if (!renderTimer) {
        renderTimer = setTimeout(function() {
          renderTimer = null;
          if (streamingContent && streamingText && typeof marked !== 'undefined') {
            streamingContent.innerHTML = marked.parse(streamingText) + '<span class="stream-cursor"></span>';
            if (typeof addCodeBlockHeaders !== 'undefined') addCodeBlockHeaders(streamingContent);
            chatMessages.scrollTop = chatMessages.scrollHeight;
          }
        }, 800);
      }
      requestAnimationFrame(typewriterTick);
    }

    _taskWs = connectRunStream(data.run_id,
      function(event) {
        if (event.type === 'assistant' && event.content) {
          if (!streamingContent) {
            hideThinking();
            streamingContent = appendChatMessage(chatMessages, 'agent', '', true);
          }
          for (var c = 0; c < event.content.length; c++) {
            typewriterQueue.push(event.content[c]);
          }
          if (!typewriterRunning) requestAnimationFrame(typewriterTick);
        }
      },
      function() {
        hideThinking();
        if (renderTimer) clearTimeout(renderTimer);
        while (typewriterQueue.length > 0) { streamingText += typewriterQueue.shift(); }
        typewriterRunning = false;
        if (streamingContent && streamingText) {
          streamingContent.classList.remove('streaming');
          if (typeof marked !== 'undefined') {
            streamingContent.innerHTML = marked.parse(streamingText);
            if (typeof addCodeBlockHeaders !== 'undefined') addCodeBlockHeaders(streamingContent);
            if (typeof hljs !== 'undefined') {
              streamingContent.querySelectorAll('pre code').forEach(function(block) {
                hljs.highlightElement(block);
              });
            }
          }
          chatMessages.scrollTop = chatMessages.scrollHeight;
        }
      },
      function() { hideThinking(); }
    );
  })
  .catch(function(err) {
    hideThinking();
    var chatMessages = document.getElementById('chat-messages');
    if (chatMessages) appendChatMessage(chatMessages, 'agent', 'Failed to start brainstorming: ' + err.message, false);
  });
}
