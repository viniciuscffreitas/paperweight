// ── Task Detail: activity feed, chat, tab switching ──

var _taskConfig = {};
var _taskWs = null;
var _typewriterQueue = [];
var _typewriterActive = false;

function _makeActionBtn(iconName, tooltip, onclick) {
  var btn = document.createElement('button');
  btn.className = 'msg-action-btn';
  btn.innerHTML = '<span class="material-icons">' + iconName + '</span><span class="tooltip">' + tooltip + '</span>';
  btn.onclick = function(e) { e.stopPropagation(); onclick(); };
  return btn;
}

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

  // Set up tab switching
  setupTabSwitching();

  // Load activity if session exists
  if (config.sessionId) {
    loadActivityFeed(config.sessionId);
  } else if (config.status === 'running' || config.status === 'pending') {
    showEmptyActivity('Waiting for agent to start...');
  } else {
    showEmptyActivity('No activity recorded');
  }
}

function setupTabSwitching() {
  // Find all tab buttons (they have data-active attribute pattern)
  var container = document.querySelector('[style*="border-bottom:1px solid var(--separator-strong)"]');
  if (!container) return;
  var buttons = container.querySelectorAll('button');
  // Detect tab names from button labels
  var tabs = [];
  buttons.forEach(function(btn) {
    tabs.push(btn.textContent.trim().toLowerCase());
  });

  buttons.forEach(function(btn, i) {
    btn.removeAttribute('hx-get'); // Prevent HTMX from firing
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      switchTab(tabs[i] || 'activity', btn, buttons);
    });
  });
}

function switchTab(tabName, activeBtn, allButtons) {
  // Update button styles
  allButtons.forEach(function(btn) {
    btn.style.color = 'var(--text-muted)';
    btn.style.borderBottom = '2px solid transparent';
    delete btn.dataset.active;
  });
  activeBtn.style.color = 'var(--text-primary)';
  activeBtn.style.borderBottom = '2px solid var(--accent-text)';
  activeBtn.dataset.active = 'true';

  // Show/hide tab content
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
          // Update last tool event detail
          var items = container.children;
          if (items.length > 0) {
            var lastItem = items[items.length - 1];
            var detail = lastItem.querySelector('[style*="text-disabled"]');
            if (detail) detail.textContent = ev.content.substring(0, 100);
          }
        }
      });

      // Set output tab content with markdown rendering
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

      // Connect WebSocket if still running
      if (_taskConfig.status === 'running') {
        connectTaskStream();
      }

      // Load chat history
      loadChatHistory(events);
    })
    .catch(function(err) {
      showEmptyActivity('Failed to load activity');
    });
}

function connectTaskStream() {
  // Get run_id from a fetch to the session events (last run)
  fetch('/api/sessions/' + _taskConfig.sessionId + '/events')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      // The run_id may be in the session data
      // For now, we'll try to connect via the session's last run
      // The WebSocket expects a run_id, so we need to find it
      // Check if there's a way to get the run_id from work item
      showThinking();
    });
}

function parseToolLabel(ev) {
  if (ev.file_path) return ev.file_path;
  var content = ev.content || '';
  try {
    var parsed = JSON.parse(content);
    // Skill tool
    if (parsed.skill) return parsed.skill + (parsed.args ? ' ' + parsed.args.substring(0, 40) : '');
    // Bash — show description or command
    if (parsed.description) return parsed.description;
    if (parsed.command) {
      var cmd = parsed.command;
      // Clean up long commands — show first meaningful part
      if (cmd.length > 60) cmd = cmd.substring(0, 57) + '...';
      return cmd;
    }
    // File operations
    if (parsed.file_path) return parsed.file_path;
    // Search tools
    if (parsed.pattern) return (parsed.glob || '') + ' ' + parsed.pattern;
    if (parsed.query) return parsed.query;
    // Agent tool
    if (parsed.prompt) return parsed.prompt.substring(0, 60);
  } catch (e) { /* not JSON */ }
  // Fallback: if content looks like JSON but couldn't parse specific fields
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

var _thinkingEl = null;

function showThinking() {
  hideThinking();
  var container = document.getElementById('chat-messages');
  if (!container) return;
  _thinkingEl = document.createElement('div');
  _thinkingEl.className = 'chat-msg agent';
  _thinkingEl.innerHTML = '<div class="chat-msg-header"><span class="material-icons chat-msg-icon agent" aria-hidden="true">smart_toy</span><div class="chat-msg-label agent">Agent</div></div>' +
    '<div class="thinking-dots"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
  container.appendChild(_thinkingEl);
  container.scrollTop = container.scrollHeight;
}

function hideThinking() {
  if (_thinkingEl && _thinkingEl.parentNode) {
    _thinkingEl.parentNode.removeChild(_thinkingEl);
  }
  _thinkingEl = null;
}

function loadChatHistory(events) {
  var chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;

  // Chat history shows only user prompts and agent responses.
  // Tool calls are visible in the Activity tab — keeping chat clean.
  events.forEach(function(ev) {
    if (ev.type === 'user_prompt' && ev.content) {
      appendChatMessage(chatMessages, 'you', ev.content, false);
    } else if (ev.type === 'assistant' && ev.content) {
      appendChatMessage(chatMessages, 'agent', ev.content, false);
    }
  });
}

function appendChatMessage(container, role, text, isStreaming) {
  var wrapper = document.createElement('div');
  wrapper.className = 'chat-msg ' + role;

  // Header: icon + label + timestamp
  var header = document.createElement('div');
  header.className = 'chat-msg-header';

  var icon = document.createElement('span');
  icon.className = 'material-icons chat-msg-icon ' + role;
  icon.textContent = role === 'you' ? 'person' : 'smart_toy';
  icon.setAttribute('aria-hidden', 'true');

  var label = document.createElement('div');
  label.className = 'chat-msg-label ' + role;
  label.textContent = role === 'you' ? 'You' : 'Agent';

  var time = document.createElement('div');
  time.className = 'chat-msg-time';
  time.textContent = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});

  header.appendChild(icon);
  header.appendChild(label);
  header.appendChild(time);

  // Actions toolbar (hover-reveal, icon buttons with tooltips)
  var actions = document.createElement('div');
  actions.className = 'msg-actions';

  // Copy button
  actions.appendChild(_makeActionBtn('content_copy', 'Copy', function() {
    navigator.clipboard.writeText(text).then(function() {
      // Brief visual feedback
      icon.style.opacity = '0.5';
      setTimeout(function() { icon.style.opacity = '1'; }, 300);
    });
  }));

  if (role === 'agent' && !isStreaming) {
    // Retry button (re-send previous user message)
    actions.appendChild(_makeActionBtn('refresh', 'Retry', function() {
      var msgs = container.querySelectorAll('.chat-msg.user');
      if (msgs.length > 0) {
        var lastUserContent = msgs[msgs.length - 1].querySelector('.chat-msg-content');
        if (lastUserContent) {
          var input = document.getElementById('chat-input');
          if (input) { input.value = lastUserContent.textContent; sendChatPrompt(); }
        }
      }
    }));
  }

  if (role === 'you') {
    // Edit button (put text back in input)
    actions.appendChild(_makeActionBtn('edit', 'Edit', function() {
      var input = document.getElementById('chat-input');
      if (input) {
        input.value = text;
        input.parentNode.dataset.replicatedValue = text;
        input.focus();
      }
    }));
  }

  // Content
  var content = document.createElement('div');
  content.className = 'chat-msg-content';
  if (isStreaming) {
    content.classList.add('streaming');
    content.textContent = text;
  } else {
    if (typeof marked !== 'undefined' && role === 'agent') {
      content.innerHTML = marked.parse(text);
      addCodeBlockHeaders(content);
      if (typeof hljs !== 'undefined') {
        content.querySelectorAll('pre code').forEach(function(block) {
          hljs.highlightElement(block);
        });
      }
    } else {
      content.textContent = text;
    }
  }

  wrapper.appendChild(header);
  wrapper.appendChild(actions);
  wrapper.appendChild(content);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
  return content;
}

function addCodeBlockHeaders(container) {
  container.querySelectorAll('pre code').forEach(function(codeBlock) {
    var pre = codeBlock.parentElement;
    // Detect language from class
    var lang = '';
    var classes = codeBlock.className.split(' ');
    for (var i = 0; i < classes.length; i++) {
      if (classes[i].startsWith('language-')) {
        lang = classes[i].replace('language-', '');
        break;
      }
    }

    var header = document.createElement('div');
    header.className = 'code-header';

    var langSpan = document.createElement('span');
    langSpan.textContent = lang || 'code';

    var copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy';
    copyBtn.onclick = function() {
      navigator.clipboard.writeText(codeBlock.textContent).then(function() {
        copyBtn.textContent = 'Copied!';
        setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1500);
      });
    };

    header.appendChild(langSpan);
    header.appendChild(copyBtn);
    pre.insertBefore(header, codeBlock);
  });
}

function renderToolCallInChat(container, event) {
  var toolName = event.tool_name || 'Tool';
  var label = parseToolLabel(event);
  if (label.length > 80) label = label.substring(0, 80) + '...';

  var colorMap = {
    'Edit': '#22c55e', 'Write': '#22c55e',
    'Bash': '#fbbf24',
    'Read': '#818cf8', 'Grep': '#818cf8', 'Glob': '#818cf8'
  };
  var color = colorMap[toolName] || '#c084fc';

  var card = document.createElement('div');
  card.className = 'tool-call';
  card.style.borderLeftColor = color;

  var header = document.createElement('div');
  header.className = 'tool-call-header';
  header.innerHTML = '<span class="arrow">&#9654;</span>' +
    '<span class="tool-name" style="color:' + color + ';">' + toolName + '</span>' +
    '<span class="tool-label">' + label + '</span>';

  var detail = document.createElement('div');
  detail.className = 'tool-call-detail';
  detail.textContent = event.content || '';

  header.onclick = function() { card.classList.toggle('expanded'); };

  card.appendChild(header);
  card.appendChild(detail);
  container.appendChild(card);
}

function sendChatPrompt() {
  var input = document.getElementById('chat-input');
  var text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.parentNode.dataset.replicatedValue = '';
  input.disabled = true;

  var chatMessages = document.getElementById('chat-messages');
  appendChatMessage(chatMessages, 'you', text, false);

  var modelSelect = document.getElementById('chat-model');
  var model = modelSelect ? modelSelect.value : 'claude-sonnet-4-6';
  var body = { prompt: text, model: model, max_cost_usd: 2.0 };
  if (_taskConfig.sessionId) body.session_id = _taskConfig.sessionId;

  showThinking();

  // Show stop button
  var sendArea = document.getElementById('chat-send-area');
  var origHTML = sendArea.innerHTML;
  sendArea.innerHTML = '<button onclick="stopGeneration()" style="background:transparent;color:var(--status-error);border:1px solid var(--status-error);padding:6px 16px;font-size:13px;font-weight:500;border-radius:8px;cursor:pointer;font-family:inherit;">Stop</button>';

  fetch('/api/projects/' + _taskConfig.projectId + '/agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(function(r) {
    if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
    return r.json();
  })
  .then(function(data) {
    _taskConfig.sessionId = data.session_id;
    // Update task's session_id in backend so reload preserves chat
    if (_taskConfig.taskId) {
      fetch('/api/work-items/' + _taskConfig.taskId, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: data.session_id})
      }).catch(function() {});
    }
    // Keep thinking visible until first content arrives

    var streamingContent = null;
    var streamingText = '';
    var typewriterQueue = [];
    var typewriterRunning = false;
    var renderTimer = null;

    function typewriterTick() {
      if (typewriterQueue.length === 0) {
        typewriterRunning = false;
        return;
      }
      typewriterRunning = true;
      // Process 2-4 chars per frame for natural speed
      var batch = Math.min(3, typewriterQueue.length);
      for (var i = 0; i < batch; i++) {
        streamingText += typewriterQueue.shift();
      }
      streamingContent.textContent = streamingText;
      // Auto-scroll
      chatMessages.scrollTop = chatMessages.scrollHeight;
      // Schedule markdown render periodically (every 800ms)
      if (!renderTimer) {
        renderTimer = setTimeout(function() {
          renderTimer = null;
          if (streamingContent && streamingText && typeof marked !== 'undefined') {
            streamingContent.innerHTML = marked.parse(streamingText) + '<span class="stream-cursor"></span>';
            addCodeBlockHeaders(streamingContent);
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
          // Queue chars for typewriter effect
          for (var c = 0; c < event.content.length; c++) {
            typewriterQueue.push(event.content[c]);
          }
          if (!typewriterRunning) requestAnimationFrame(typewriterTick);
        } else if (event.type === 'tool_use') {
          renderToolCallInChat(chatMessages, event);
          var eventsContainer = document.getElementById('activity-events');
          if (eventsContainer) {
            renderActivityEvent(eventsContainer, event.tool_name || 'Tool', parseToolLabel(event), '');
          }
        }
      },
      function() {
        // Stream complete — flush typewriter queue and final markdown render
        hideThinking();
        if (renderTimer) clearTimeout(renderTimer);
        // Drain remaining typewriter chars
        while (typewriterQueue.length > 0) {
          streamingText += typewriterQueue.shift();
        }
        typewriterRunning = false;
        if (streamingContent && streamingText) {
          streamingContent.classList.remove('streaming');
          if (typeof marked !== 'undefined') {
            streamingContent.innerHTML = marked.parse(streamingText);
            addCodeBlockHeaders(streamingContent);
            if (typeof hljs !== 'undefined') {
              streamingContent.querySelectorAll('pre code').forEach(function(block) {
                hljs.highlightElement(block);
              });
            }
          }
          chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        input.disabled = false;
        input.focus();
        sendArea.innerHTML = origHTML;
        _taskWs = null;
      },
      function() {
        hideThinking();
        appendChatMessage(chatMessages, 'agent', 'Connection error. Try again.', false);
        input.disabled = false;
        sendArea.innerHTML = origHTML;
        _taskWs = null;
      }
    );
  })
  .catch(function(err) {
    hideThinking();
    appendChatMessage(chatMessages, 'agent', 'Error: ' + err.message, false);
    input.disabled = false;
    sendArea.innerHTML = origHTML;
  });
}

function stopGeneration() {
  if (_taskWs) {
    _taskWs.close();
    _taskWs = null;
  }
}

function cancelRun() {
  fetch('/api/sessions/' + _taskConfig.sessionId + '/events')
    .then(function(r) { return r.json(); })
    .then(function() {
      window.location.reload();
    });
}

function startTask() {
  var btn = document.querySelector('[onclick="startTask()"]');
  if (btn) { btn.textContent = 'Starting...'; btn.style.opacity = '0.6'; btn.disabled = true; }

  // Get task description to use as prompt
  var desc = document.getElementById('task-description');
  var prompt = desc ? desc.textContent.trim() : document.querySelector('[style*="font-size:20px"]').textContent.trim();

  var modelSelect = document.getElementById('chat-model');
  var model = modelSelect ? modelSelect.value : 'claude-sonnet-4-6';

  // Start agent with task description as prompt
  fetch('/api/projects/' + _taskConfig.projectId + '/agent', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ prompt: prompt, model: model, max_cost_usd: 5.0 })
  })
  .then(function(r) { return r.json(); })
  .then(function(data) {
    // Link session to task
    _taskConfig.sessionId = data.session_id;
    fetch('/api/work-items/' + _taskConfig.taskId, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ session_id: data.session_id, status: 'running' })
    }).then(function() {
      window.location.reload();
    });
  })
  .catch(function(err) {
    if (btn) { btn.textContent = 'Start'; btn.style.opacity = '1'; btn.disabled = false; }
    alert('Failed to start: ' + err.message);
  });
}

function rerunTask() {
  fetch('/api/work-items/' + _taskConfig.taskId + '/rerun', { method: 'POST' })
    .then(function() {
      window.location.reload();
    });
}
