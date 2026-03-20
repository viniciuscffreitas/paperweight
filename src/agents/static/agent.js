// ── Agent Tab: terminal-like CLI experience ──

var _agentSessionId = null;
var _agentWs = null;
var _thinkingEl = null;

// Read session ID from data attribute and load history if session exists
(function() {
  var el = document.getElementById('agent-session-status');
  if (el && el.dataset.sessionId) {
    _agentSessionId = el.dataset.sessionId;
    loadSessionHistory(_agentSessionId);
  }
})();

function loadSessionHistory(sessionId) {
  fetch('/api/sessions/' + sessionId + '/events')
  .then(function(r) { return r.json(); })
  .then(function(events) {
    if (!events.length) return;
    var output = document.getElementById('agent-output');
    if (!output) return;
    // Clear placeholder
    var ph = output.querySelector('[style*="font-style:italic"]');
    if (ph) ph.remove();

    var lastType = '';
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      if (ev.type === 'user_prompt') {
        appendBlock(output, 'div', 'you', {color:'#6b7280', fontSize:'10px', marginTop:'14px'});
        appendBlock(output, 'div', ev.content, {color:'#e8eaed', marginBottom:'14px', paddingLeft:'2px', fontSize:'13px'});
        lastType = 'user';
      } else if (ev.type === 'assistant' && ev.content) {
        if (lastType !== 'agent') {
          appendBlock(output, 'div', 'agent', {color:'#3b82f6', fontSize:'10px'});
          lastType = 'agent';
        }
        renderAgentEvent(ev, output);
      } else if (ev.type === 'tool_use' || ev.type === 'tool_result') {
        if (lastType !== 'agent') {
          appendBlock(output, 'div', 'agent', {color:'#3b82f6', fontSize:'10px'});
          lastType = 'agent';
        }
        renderAgentEvent(ev, output);
      } else if (ev.type === 'task_completed' || ev.type === 'task_failed') {
        var clr = ev.type === 'task_completed' ? '#22c55e' : '#f85149';
        var icon = ev.type === 'task_completed' ? '\u2713 ' : '\u2717 ';
        appendBlock(output, 'div', icon + (ev.content || ''), {color:clr, margin:'10px 0', paddingLeft:'2px', fontSize:'12px'});
        lastType = '';
      }
    }
    output.scrollTop = output.scrollHeight;
  })
  .catch(function() {}); // silently fail — session may have no events
}

function sendAgentPrompt(projectId) {
  var input = document.getElementById('agent-input');
  var prompt = input.value.trim();
  if (!prompt) return;

  var output = document.getElementById('agent-output');
  // Clear placeholder on first use
  var ph = output.querySelector('[style*="font-style:italic"]');
  if (ph) ph.remove();

  // Render user prompt
  appendBlock(output, 'div', 'you', {color:'#6b7280', fontSize:'10px', marginTop:'14px'});
  appendBlock(output, 'div', prompt, {color:'#e8eaed', marginBottom:'14px', paddingLeft:'2px', fontSize:'13px'});
  output.scrollTop = output.scrollHeight;

  input.value = '';
  input.disabled = true;
  input.placeholder = 'Pensando...';

  var model = document.getElementById('agent-model').value;
  var budget = parseFloat(document.getElementById('agent-budget').value) || 2.0;
  var body = { prompt: prompt, model: model, max_cost_usd: budget };
  if (_agentSessionId) body.session_id = _agentSessionId;

  // Show thinking indicator
  showThinking(output);

  fetch('/api/projects/' + projectId + '/agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(function(r) {
    if (!r.ok) return r.text().then(function(t) { throw new Error(t); });
    return r.json();
  })
  .then(function(data) {
    _agentSessionId = data.session_id;
    updateSessionStatus(data.session_id);
    connectAgentStream(data.run_id, output, input);
  })
  .catch(function(err) {
    hideThinking();
    appendBlock(output, 'div', 'Erro: ' + err.message, {color:'#f85149', margin:'8px 0'});
    input.disabled = false;
    input.placeholder = 'Tente novamente...';
  });
}

function showThinking(output) {
  hideThinking();
  _thinkingEl = document.createElement('div');
  _thinkingEl.style.cssText = 'display:flex;align-items:center;gap:6px;padding:8px 2px;';
  _thinkingEl.innerHTML =
    '<span style="color:#3b82f6;font-size:10px;">agent</span>' +
    '<span style="color:#3b82f6;font-size:12px;animation:thinking-pulse 1.5s ease-in-out infinite;">pensando</span>' +
    '<span style="color:#3b82f6;animation:thinking-pulse 1.5s ease-in-out infinite 0.2s;">.</span>' +
    '<span style="color:#3b82f6;animation:thinking-pulse 1.5s ease-in-out infinite 0.4s;">.</span>' +
    '<span style="color:#3b82f6;animation:thinking-pulse 1.5s ease-in-out infinite 0.6s;">.</span>';
  output.appendChild(_thinkingEl);
  output.scrollTop = output.scrollHeight;
}

function hideThinking() {
  if (_thinkingEl && _thinkingEl.parentNode) {
    _thinkingEl.parentNode.removeChild(_thinkingEl);
  }
  _thinkingEl = null;
}

function connectAgentStream(runId, output, input) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs/' + runId);
  _agentWs = ws;
  var firstEvent = true;

  ws.onmessage = function(e) {
    try {
      var event = JSON.parse(e.data);
      // Remove thinking indicator on first real event
      if (firstEvent && (event.type === 'assistant' || event.type === 'tool_use')) {
        hideThinking();
        appendBlock(output, 'div', 'agent', {color:'#3b82f6', fontSize:'10px'});
        firstEvent = false;
      }
      renderAgentEvent(event, output);
      output.scrollTop = output.scrollHeight;
    } catch(err) {
      appendBlock(output, 'div', '[erro de stream: ' + err.message + ']',
        {color:'#f85149', fontSize:'10px', margin:'2px 0'});
    }
  };
  ws.onclose = function() {
    hideThinking();
    input.disabled = false;
    input.placeholder = 'Continuar a sessão...';
    input.focus();
  };
  ws.onerror = function() {
    hideThinking();
    appendBlock(output, 'div', '[erro de conexão]',
      {color:'#f85149', margin:'4px 0', paddingLeft:'2px'});
    input.disabled = false;
    input.placeholder = 'Tente novamente...';
  };
}

function renderAgentEvent(event, output) {
  var type = event.type;
  var content = event.content || '';
  var toolName = event.tool_name || '';
  var filePath = event.file_path || '';

  if (type === 'assistant' && content) {
    var div = document.createElement('div');
    div.style.cssText = 'color:#c8ccd4;margin:4px 0;padding-left:2px;white-space:pre-wrap;font-size:13px;line-height:1.7;';
    div.textContent = content;
    output.appendChild(div);
  }
  else if (type === 'tool_use') {
    hideThinking(); // in case thinking is still visible

    var color = '#a78bfa';
    if (['Edit','Write'].indexOf(toolName) >= 0) color = '#22c55e';
    if (toolName === 'Bash') color = '#f59e0b';
    var label = filePath || content.substring(0, 80);

    var wrapper = document.createElement('div');
    wrapper.style.cssText = 'margin:6px 0;border-left:2px solid ' + color + ';padding-left:10px;';

    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:6px;cursor:pointer;padding:2px 0;';

    var arrow = document.createElement('span');
    arrow.style.cssText = 'color:#6b7280;font-size:10px;transition:transform .15s;';
    arrow.textContent = '\u25B6';

    var nameSpan = document.createElement('span');
    nameSpan.style.cssText = 'color:' + color + ';font-size:11px;font-weight:700;';
    nameSpan.textContent = toolName;

    var labelSpan = document.createElement('span');
    labelSpan.style.cssText = 'color:#8b8fa3;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    labelSpan.textContent = label;

    header.appendChild(arrow);
    header.appendChild(nameSpan);
    header.appendChild(labelSpan);

    var detail = document.createElement('div');
    detail.style.cssText = 'display:none;background:#0d1117;border-radius:4px;padding:8px 10px;font-size:11px;'
      + 'margin-top:4px;max-height:200px;overflow:auto;white-space:pre-wrap;color:#8b8fa3;line-height:1.5;';
    detail.textContent = content;
    detail.dataset.toolDetail = 'true';

    header.addEventListener('click', function() {
      var visible = detail.style.display !== 'none';
      detail.style.display = visible ? 'none' : 'block';
      arrow.textContent = visible ? '\u25B6' : '\u25BC';
    });

    wrapper.appendChild(header);
    wrapper.appendChild(detail);
    output.appendChild(wrapper);
  }
  else if (type === 'tool_result') {
    var details = output.querySelectorAll('[data-tool-detail]');
    if (details.length) {
      var last = details[details.length - 1];
      last.textContent = content.substring(0, 500);
      last.style.display = 'block';
      var prevHeader = last.previousElementSibling;
      if (prevHeader) {
        var arrowEl = prevHeader.querySelector('span');
        if (arrowEl) arrowEl.textContent = '\u25BC';
      }
    }
  }
  else if (type === 'task_completed' || type === 'task_failed') {
    hideThinking();
    var clr = type === 'task_completed' ? '#22c55e' : '#f85149';
    var icon = type === 'task_completed' ? '\u2713 ' : '\u2717 ';
    appendBlock(output, 'div', icon + content, {color:clr, margin:'10px 0', paddingLeft:'2px', fontSize:'12px'});
    var input = document.getElementById('agent-input');
    if (input) { input.disabled = false; input.placeholder = 'Continuar a sessão...'; input.focus(); }
    if (_agentWs) { _agentWs.close(); _agentWs = null; }
  }
  // Skip 'result' type — duplicates 'assistant' content
}

function updateSessionStatus(sessionId) {
  var el = document.getElementById('agent-session-status');
  if (el) {
    el.textContent = 'session: ' + sessionId.substring(0, 8);
    el.dataset.sessionId = sessionId;
  }
}

function endAgentSession(sessionId) {
  fetch('/api/sessions/' + sessionId + '/close', { method: 'POST' })
  .then(function(r) {
    if (!r.ok) throw new Error('Falha ao encerrar sessão (status ' + r.status + ')');
    _agentSessionId = null;
    var s = document.getElementById('agent-session-status');
    if (s) { s.textContent = 'sem sessão'; s.dataset.sessionId = ''; }
    var o = document.getElementById('agent-output');
    if (o) appendBlock(o, 'div', 'Sessão encerrada.', {color:'#6b7280', margin:'12px 0', fontStyle:'italic', fontSize:'12px'});
    var i = document.getElementById('agent-input');
    if (i) i.placeholder = 'Escreva uma instrução...';
  })
  .catch(function(err) {
    var o = document.getElementById('agent-output');
    if (o) appendBlock(o, 'div', 'Erro: ' + err.message, {color:'#f85149', margin:'8px 0'});
  });
}

// ── DOM helpers ──

function appendBlock(parent, tag, text, styles) {
  var el = document.createElement(tag);
  el.textContent = text;
  if (styles) {
    for (var k in styles) {
      if (styles.hasOwnProperty(k)) el.style[k] = styles[k];
    }
  }
  parent.appendChild(el);
  return el;
}
