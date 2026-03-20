// ── Chat: message rendering, history, multimodal, streaming ──
// Depends on global state declared in task-detail.js:
//   _taskConfig, _taskWs, _chatAttachments, _voiceRecognition, _voiceActive

var _thinkingEl = null;

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
}

function hideThinking() {
  if (_thinkingEl && _thinkingEl.parentNode) {
    _thinkingEl.parentNode.removeChild(_thinkingEl);
  }
  _thinkingEl = null;
}

// ── Message rendering ──

function appendChatMessage(container, role, text, isStreaming, attachments) {
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

// ── Chat history ──

function loadChatHistory(events) {
  var chatMessages = document.getElementById('chat-messages');
  if (!chatMessages) return;

  // Chat history shows only user prompts and agent responses.
  // Tool calls are visible in the Activity tab — keeping chat clean.
  // Consecutive assistant messages are merged into one bubble.
  var pendingAgentText = '';

  events.forEach(function(ev) {
    if (ev.type === 'user_prompt' && ev.content) {
      // Flush pending agent text first
      if (pendingAgentText) {
        appendChatMessage(chatMessages, 'agent', pendingAgentText.trim(), false);
        pendingAgentText = '';
      }
      var userText = ev.content;
      // Clean up auto-generated prompts
      if (userText.startsWith('Implement the spec at ')) {
        userText = 'Started task from spec';
      } else if (userText.startsWith('# Task:')) {
        userText = userText.split('\n')[0].replace('# Task: ', '').trim();
      } else if (userText.length > 200) {
        userText = userText.substring(0, 200) + '...';
      }
      appendChatMessage(chatMessages, 'you', userText, false);
    } else if (ev.type === 'assistant' && ev.content) {
      // Accumulate consecutive agent messages
      pendingAgentText += ev.content + '\n\n';
    }
  });
  // Flush remaining agent text
  if (pendingAgentText) {
    appendChatMessage(chatMessages, 'agent', pendingAgentText.trim(), false);
  }
}

// ── Multimodal: image attachments ──

function initMultimodal() {
  var chatContent = document.getElementById('chat-content');
  var input = document.getElementById('chat-input');
  if (!chatContent || !input) return;

  // Paste: intercept images pasted into the textarea
  input.addEventListener('paste', function(e) {
    var items = (e.clipboardData || window.clipboardData).items;
    var hasImage = false;
    for (var i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        hasImage = true;
        var file = items[i].getAsFile();
        if (file) addAttachmentFile(file);
      }
    }
    if (hasImage) e.preventDefault();
  });

  // Drag-and-drop onto the chat panel
  chatContent.addEventListener('dragover', function(e) {
    if (e.dataTransfer.types && Array.prototype.some.call(e.dataTransfer.types, function(t) {
      return t === 'Files';
    })) {
      e.preventDefault();
      chatContent.classList.add('drag-over');
    }
  });
  chatContent.addEventListener('dragleave', function(e) {
    if (!chatContent.contains(e.relatedTarget)) {
      chatContent.classList.remove('drag-over');
    }
  });
  chatContent.addEventListener('drop', function(e) {
    e.preventDefault();
    chatContent.classList.remove('drag-over');
    var files = e.dataTransfer.files;
    for (var i = 0; i < files.length; i++) {
      if (files[i].type.startsWith('image/')) addAttachmentFile(files[i]);
    }
  });
}

function addAttachmentFile(file) {
  var reader = new FileReader();
  reader.onload = function(e) {
    var dataUrl = e.target.result;
    var idx = _chatAttachments.length;
    _chatAttachments.push({ dataUrl: dataUrl, path: null, filename: file.name });
    renderAttachmentStrip();
    _uploadAttachment(idx, dataUrl, file.type);
  };
  reader.readAsDataURL(file);
}

function _uploadAttachment(idx, dataUrl, mimeType) {
  fetch('/api/uploads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: dataUrl, mime_type: mimeType })
  })
  .then(function(r) { return r.ok ? r.json() : null; })
  .then(function(data) {
    if (data && _chatAttachments[idx]) {
      _chatAttachments[idx].path = data.path;
    }
  })
  .catch(function() { /* upload failed; path stays null, skip in prompt */ });
}

function renderAttachmentStrip() {
  var strip = document.getElementById('chat-attachment-strip');
  if (!strip) return;
  strip.innerHTML = '';
  if (_chatAttachments.length === 0) {
    strip.style.display = 'none';
    return;
  }
  strip.style.display = 'flex';
  _chatAttachments.forEach(function(att, i) {
    var thumb = document.createElement('div');
    thumb.className = 'attachment-thumb';

    var img = document.createElement('img');
    img.src = att.dataUrl;
    img.alt = att.filename || 'image';

    var removeBtn = document.createElement('button');
    removeBtn.className = 'attachment-thumb-remove';
    removeBtn.innerHTML = '&#x2715;';
    removeBtn.title = 'Remove';
    removeBtn.onclick = function(e) {
      e.stopPropagation();
      _chatAttachments.splice(i, 1);
      renderAttachmentStrip();
    };

    thumb.appendChild(img);
    thumb.appendChild(removeBtn);
    strip.appendChild(thumb);
  });
}

function handleFileInput(input) {
  var files = input.files;
  for (var i = 0; i < files.length; i++) {
    if (files[i].type.startsWith('image/')) addAttachmentFile(files[i]);
  }
  input.value = '';
}

// ── Multimodal: push-to-talk voice ──

function startVoice() {
  if (_voiceActive) return;
  var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    var btn = document.getElementById('chat-voice-btn');
    if (btn) { btn.title = 'Voice not supported in this browser'; }
    return;
  }
  _voiceRecognition = new SpeechRecognition();
  _voiceRecognition.continuous = false;
  _voiceRecognition.interimResults = true;
  _voiceRecognition.lang = navigator.language || 'en-US';

  var input = document.getElementById('chat-input');
  var baseText = input ? input.value : '';

  _voiceRecognition.onresult = function(e) {
    var transcript = '';
    for (var i = 0; i < e.results.length; i++) {
      transcript += e.results[i][0].transcript;
    }
    if (input) {
      input.value = baseText + (baseText && transcript ? ' ' : '') + transcript;
      input.parentNode.dataset.replicatedValue = input.value;
    }
  };

  _voiceRecognition.onend = function() {
    _voiceActive = false;
    var btn = document.getElementById('chat-voice-btn');
    if (btn) btn.classList.remove('recording');
  };

  _voiceRecognition.start();
  _voiceActive = true;
  var btn = document.getElementById('chat-voice-btn');
  if (btn) btn.classList.add('recording');
}

function stopVoice() {
  if (_voiceRecognition && _voiceActive) {
    _voiceRecognition.stop();
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
  var body = { prompt: promptText, model: model, max_cost_usd: 2.0 };
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
