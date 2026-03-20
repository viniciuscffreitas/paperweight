// ── Task Detail: activity feed, chat, tab switching ──

var _taskConfig = {};
var _taskWs = null;
var _typewriterQueue = [];
var _typewriterActive = false;

function initTaskDetail(config) {
  _taskConfig = config;

  // Set up tab switching
  var tabButtons = document.querySelectorAll('#task-tab-content ~ div button, div[style*="border-bottom"] button');
  // Actually, we need to find the tab bar buttons
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
  var tabs = ['activity', 'output', 'chat'];

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
  var activity = document.getElementById('activity-feed');
  var output = document.getElementById('output-content');
  var chat = document.getElementById('chat-content');

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
          renderActivityEvent(container, ev.tool_name || 'Tool', ev.file_path || ev.content, '');
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

      // Set output tab content
      var outputText = document.getElementById('output-text');
      if (outputText && lastOutput) {
        outputText.textContent = lastOutput.trim();
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
  _thinkingEl.className = 'chat-msg';
  _thinkingEl.innerHTML = '<div class="chat-msg-label agent">agent</div>' +
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

  events.forEach(function(ev) {
    if (ev.type === 'user_prompt' && ev.content) {
      appendChatMessage(chatMessages, 'you', ev.content, false);
    } else if (ev.type === 'assistant' && ev.content) {
      appendChatMessage(chatMessages, 'agent', ev.content, false);
    } else if (ev.type === 'tool_use') {
      renderToolCallInChat(chatMessages, ev);
    }
  });
}

function appendChatMessage(container, role, text, isStreaming) {
  var wrapper = document.createElement('div');
  wrapper.className = 'chat-msg';

  var label = document.createElement('div');
  label.className = 'chat-msg-label ' + role;
  label.textContent = role === 'you' ? 'you' : 'agent';

  var content = document.createElement('div');
  content.className = 'chat-msg-content';
  if (isStreaming) {
    content.classList.add('streaming');
    content.textContent = text;
  } else {
    // Render markdown for completed messages
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

  wrapper.appendChild(label);
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
  var label = event.file_path || event.content || '';
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

  var body = { prompt: text, model: 'claude-sonnet-4-6', max_cost_usd: 2.0 };
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
    hideThinking();

    var streamingContent = null;
    var streamingText = '';

    _taskWs = connectRunStream(data.run_id,
      function(event) {
        if (event.type === 'assistant' && event.content) {
          if (!streamingContent) {
            streamingContent = appendChatMessage(chatMessages, 'agent', '', true);
          }
          streamingText += event.content;
          streamingContent.textContent = streamingText;
          chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (event.type === 'tool_use') {
          renderToolCallInChat(chatMessages, event);
          // Also add to activity feed
          var eventsContainer = document.getElementById('activity-events');
          if (eventsContainer) {
            renderActivityEvent(eventsContainer, event.tool_name || 'Tool', event.file_path || event.content, '');
          }
        }
      },
      function() {
        // Stream complete — finalize markdown
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

function rerunTask() {
  fetch('/api/work-items/' + _taskConfig.taskId + '/rerun', { method: 'POST' })
    .then(function() {
      window.location.reload();
    });
}
