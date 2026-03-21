// ── Chat: message rendering, history, multimodal, streaming ──
// Depends on global state declared in task-detail.js:
//   _taskConfig, _taskWs, _chatAttachments, _voiceRecognition, _voiceActive

var _thinkingEl = null;
var _thinkingTimeout = null;

// ── Utility ──

function _makeActionBtn(iconName, tooltip, onclick) {
  var btn = document.createElement('button');
  btn.className = 'msg-action-btn';
  btn.innerHTML = '<span class="material-icons">' + iconName + '</span><span class="tooltip">' + tooltip + '</span>';
  btn.onclick = function(e) { e.stopPropagation(); onclick(); };
  return btn;
}

// ── Thinking indicator ──

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
  _thinkingTimeout = setTimeout(function() {
    if (_thinkingEl) {
      _thinkingEl.style.transition = 'opacity 0.3s';
      _thinkingEl.style.opacity = '0';
      setTimeout(hideThinking, 300);
    }
  }, 30000);
}

function hideThinking() {
  if (_thinkingTimeout) { clearTimeout(_thinkingTimeout); _thinkingTimeout = null; }
  if (_thinkingEl && _thinkingEl.parentNode) {
    _thinkingEl.parentNode.removeChild(_thinkingEl);
  }
  _thinkingEl = null;
}

// ── Message rendering ──

function _formatTimestamp(ts) {
  var d = ts ? new Date(ts * 1000) : new Date();
  return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false});
}

function appendChatMessage(container, role, text, isStreaming, attachments, timestamp) {
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
  time.textContent = _formatTimestamp(timestamp);

  header.appendChild(icon);
  header.appendChild(label);
  header.appendChild(time);

  // Actions toolbar (hover-reveal, icon buttons with tooltips)
  var actions = document.createElement('div');
  actions.className = 'msg-actions';

  // Copy button
  actions.appendChild(_makeActionBtn('content_copy', 'Copy', function() {
    navigator.clipboard.writeText(text).then(function() {
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

  // Render attached images above text content (user messages only)
  if (attachments && attachments.length > 0) {
    attachments.forEach(function(att) {
      var img = document.createElement('img');
      img.src = att.dataUrl;
      img.alt = att.filename || 'image';
      img.className = 'chat-msg-img';
      img.onclick = function() { window.open(att.dataUrl, '_blank'); };
      wrapper.appendChild(img);
    });
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
    langSpan.textContent = lang || '';

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

var _toolGroupEl = null;
var _toolGroupCount = 0;
var _toolGroupList = null;

function resetToolGroup() {
  _toolGroupEl = null;
  _toolGroupCount = 0;
  _toolGroupList = null;
}

function renderToolCallInChat(container, event) {
  var toolName = event.tool_name || 'Tool';
  var label = parseToolLabel(event);
  if (label.length > 60) label = label.substring(0, 57) + '...';

  var colorMap = {
    'Edit': '#22c55e', 'Write': '#22c55e',
    'Bash': '#fbbf24',
    'Read': '#818cf8', 'Grep': '#818cf8', 'Glob': '#818cf8',
    'Agent': '#c084fc', 'Skill': '#c084fc'
  };
  var color = colorMap[toolName] || '#c084fc';

  // Create or reuse tool group card
  if (!_toolGroupEl || !container.contains(_toolGroupEl)) {
    _toolGroupEl = document.createElement('div');
    _toolGroupEl.className = 'chat-msg agent tool-group';
    _toolGroupEl.innerHTML =
      '<div class="tool-group-header" onclick="this.parentElement.classList.toggle(\'expanded\')">' +
        '<span class="material-icons" style="font-size:14px;color:var(--accent-text);">build</span>' +
        '<span class="tool-group-summary">Working...</span>' +
        '<span class="material-icons tool-group-chevron" style="font-size:16px;color:var(--text-muted);transition:transform .15s;">expand_more</span>' +
      '</div>' +
      '<div class="tool-group-items"></div>';
    _toolGroupList = _toolGroupEl.querySelector('.tool-group-items');
    _toolGroupCount = 0;
    container.appendChild(_toolGroupEl);
  }

  _toolGroupCount++;

  // Update summary
  var summary = _toolGroupEl.querySelector('.tool-group-summary');
  summary.textContent = _toolGroupCount + ' tool' + (_toolGroupCount > 1 ? 's' : '') + ' used';

  // Add tool item
  var item = document.createElement('div');
  item.className = 'tool-group-item';
  item.innerHTML =
    '<span class="tool-group-dot" style="background:' + color + ';"></span>' +
    '<span class="tool-group-name" style="color:' + color + ';">' + toolName + '</span>' +
    '<span class="tool-group-label">' + label + '</span>';
  _toolGroupList.appendChild(item);

  // Auto-scroll
  container.scrollTop = container.scrollHeight;
}

// ── Chat history ──

function loadChatHistory(events) {
  var chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;

  // Chat history shows only user prompts and agent responses.
  // Tool calls are visible in the Activity tab — keeping chat clean.
  // Consecutive assistant messages are merged into one bubble.
  var pendingAgentText = '';
  var pendingAgentTs = null;
  var isFirstRun = true;

  events.forEach(function(ev) {
    if (ev.type === 'user_prompt' && ev.content) {
      // Flush pending agent text first
      if (pendingAgentText) {
        appendChatMessage(chatMessages, 'agent', pendingAgentText.trim(), false, null, pendingAgentTs);
        pendingAgentText = '';
        pendingAgentTs = null;
      }
      // Run separator between runs (skip before the very first)
      if (!isFirstRun) {
        var sep = document.createElement('div');
        sep.className = 'run-separator';
        var ts = ev.timestamp ? _formatTimestamp(ev.timestamp) : '';
        sep.innerHTML = '<span>Run started' + (ts ? ' \u00b7 ' + ts : '') + '</span>';
        chatMessages.appendChild(sep);
      }
      isFirstRun = false;
      var userText = ev.content;
      // Clean up auto-generated prompts
      if (userText.startsWith('Implement the spec at ')) {
        userText = 'Started task from spec';
      } else if (userText.startsWith('# Task:')) {
        userText = userText.split('\n')[0].replace('# Task: ', '').trim();
      } else if (userText.length > 200) {
        userText = userText.substring(0, 200) + '...';
      }
      appendChatMessage(chatMessages, 'you', userText, false, null, ev.timestamp);
    } else if (ev.type === 'assistant' && ev.content) {
      // Accumulate consecutive agent messages
      if (!pendingAgentTs) pendingAgentTs = ev.timestamp;
      pendingAgentText += ev.content + '\n\n';
    }
  });
  // Flush remaining agent text
  if (pendingAgentText) {
    appendChatMessage(chatMessages, 'agent', pendingAgentText.trim(), false, null, pendingAgentTs);
  }
}

// ── Chat send / stream ──

function sendChatPrompt() {
  var input = document.getElementById('chat-input');
  var text = input.value.trim();
  if (!text && _chatAttachments.length === 0) return;

  input.value = '';
  input.parentNode.dataset.replicatedValue = '';
  input.disabled = true;

  var chatMessages = document.getElementById('chat-messages');

  var pendingAttachments = _chatAttachments.slice();
  _chatAttachments = [];
  renderAttachmentStrip();

  var promptText = text;
  var attachedPaths = pendingAttachments
    .map(function(a) { return a.path; })
    .filter(function(p) { return !!p; });
  if (attachedPaths.length > 0) {
    promptText = (promptText ? promptText + '\n\n' : '') +
      'I have attached ' + attachedPaths.length + ' image' + (attachedPaths.length > 1 ? 's' : '') +
      ' for you to review:\n' +
      attachedPaths.map(function(p) { return '- ' + p; }).join('\n');
  }

  appendChatMessage(chatMessages, 'you', text || '(image)', false, pendingAttachments);

  var modelSelect = document.getElementById('chat-model');
  var model = modelSelect ? modelSelect.value : 'claude-sonnet-4-6';
  var body = { prompt: promptText, model: model, max_cost_usd: 5.0 };
  if (_taskConfig.sessionId) body.session_id = _taskConfig.sessionId;

  showThinking();

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
    if (_taskConfig.taskId) {
      fetch('/api/work-items/' + _taskConfig.taskId, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: data.session_id})
      }).catch(function() {});
    }

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
      var batch = Math.min(3, typewriterQueue.length);
      for (var i = 0; i < batch; i++) {
        streamingText += typewriterQueue.shift();
      }
      streamingContent.textContent = streamingText;
      chatMessages.scrollTop = chatMessages.scrollHeight;
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
        hideThinking();
        if (renderTimer) clearTimeout(renderTimer);
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
