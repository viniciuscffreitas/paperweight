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

function showThinking() {
  var el = document.getElementById('thinking-indicator');
  if (el) el.style.display = 'block';
}

function hideThinking() {
  var el = document.getElementById('thinking-indicator');
  if (el) el.style.display = 'none';
}

function loadChatHistory(events) {
  var chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;

  events.forEach(function(ev) {
    if (ev.type === 'user_prompt' && ev.content) {
      appendChatMessage(chatMessages, 'you', ev.content);
    } else if (ev.type === 'assistant' && ev.content) {
      appendChatMessage(chatMessages, 'agent', ev.content);
    }
  });
}

function appendChatMessage(container, role, text) {
  var wrapper = document.createElement('div');
  wrapper.style.cssText = 'margin-bottom:12px;';

  var label = document.createElement('div');
  label.style.cssText = 'font-size:10px;color:' + (role === 'you' ? 'var(--text-muted)' : 'var(--accent-text)') + ';margin-bottom:2px;';
  label.textContent = role;

  var content = document.createElement('div');
  content.style.cssText = 'font-size:13px;color:var(--text-primary);white-space:pre-wrap;line-height:1.7;';
  content.textContent = text;

  wrapper.appendChild(label);
  wrapper.appendChild(content);
  container.appendChild(wrapper);
}

function sendChatPrompt() {
  var input = document.getElementById('chat-input');
  var text = input.value.trim();
  if (!text) return;

  input.value = '';
  input.disabled = true;
  input.placeholder = 'Thinking...';

  var chatMessages = document.getElementById('chat-messages');
  appendChatMessage(chatMessages, 'you', text);

  var body = { prompt: text, model: 'claude-sonnet-4-6', max_cost_usd: 2.0 };
  if (_taskConfig.sessionId) body.session_id = _taskConfig.sessionId;

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
    // Connect to stream for response
    var ws = connectRunStream(data.run_id,
      function(event) {
        if (event.type === 'assistant' && event.content) {
          appendChatMessage(chatMessages, 'agent', event.content);
        } else if (event.type === 'tool_use') {
          var eventsContainer = document.getElementById('activity-events');
          renderActivityEvent(eventsContainer, event.tool_name || 'Tool', event.file_path || event.content, '');
        }
        chatMessages.scrollTop = chatMessages.scrollHeight;
      },
      function() {
        input.disabled = false;
        input.placeholder = 'Send a message...';
        input.focus();
      },
      function() {
        input.disabled = false;
        input.placeholder = 'Connection error. Try again...';
      }
    );
  })
  .catch(function(err) {
    appendChatMessage(chatMessages, 'agent', 'Error: ' + err.message);
    input.disabled = false;
    input.placeholder = 'Try again...';
  });
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
