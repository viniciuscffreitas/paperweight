// ── Agent Tab: terminal-like CLI experience ──

var _agentSessionId = null;
var _agentWs = null;

// Read session ID from data attribute (NOT from truncated display text)
(function() {
  var el = document.getElementById('agent-session-status');
  if (el && el.dataset.sessionId) _agentSessionId = el.dataset.sessionId;
})();

function sendAgentPrompt(projectId) {
  var input = document.getElementById('agent-input');
  var prompt = input.value.trim();
  if (!prompt) return;

  var output = document.getElementById('agent-output');
  // Clear placeholder on first use
  var ph = output.querySelector('[style*="font-style:italic"]');
  if (ph) ph.remove();

  // Render user prompt client-side (using DOM methods, not innerHTML)
  appendBlock(output, 'div', 'you', {color:'#6b7280', fontSize:'10px', marginTop:'12px'});
  appendBlock(output, 'div', prompt, {color:'#e0e0e0', marginBottom:'12px', paddingLeft:'2px'});
  output.scrollTop = output.scrollHeight;

  input.value = '';
  input.disabled = true;
  input.placeholder = 'Running...';

  var model = document.getElementById('agent-model').value;
  var budget = parseFloat(document.getElementById('agent-budget').value) || 2.0;
  var body = { prompt: prompt, model: model, max_cost_usd: budget };
  if (_agentSessionId) body.session_id = _agentSessionId;

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
    appendBlock(output, 'div', 'agent', {color:'#3b82f6', fontSize:'10px'});
    connectAgentStream(data.run_id, output, input);
  })
  .catch(function(err) {
    appendBlock(output, 'div', 'Error: ' + err.message, {color:'#f85149', margin:'8px 0'});
    input.disabled = false;
    input.placeholder = 'Try again...';
  });
}

function connectAgentStream(runId, output, input) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs/' + runId);
  _agentWs = ws;

  ws.onmessage = function(e) {
    try {
      var event = JSON.parse(e.data);
      renderAgentEvent(event, output);
      output.scrollTop = output.scrollHeight;
    } catch(err) {
      appendBlock(output, 'div', '[stream parse error: ' + err.message + ']',
        {color:'#f85149', fontSize:'10px', margin:'2px 0'});
    }
  };
  ws.onclose = function() {
    input.disabled = false;
    input.placeholder = 'Continue the session...';
    input.focus();
  };
  ws.onerror = function() {
    appendBlock(output, 'div', '[connection error]',
      {color:'#f85149', margin:'4px 0', paddingLeft:'2px'});
    input.disabled = false;
    input.placeholder = 'Try again...';
  };
}

function renderAgentEvent(event, output) {
  var type = event.type;
  var content = event.content || '';
  var toolName = event.tool_name || '';
  var filePath = event.file_path || '';

  if (type === 'assistant' && content) {
    var div = document.createElement('div');
    div.style.cssText = 'color:#c0c4d6;margin:4px 0;padding-left:2px;white-space:pre-wrap;';
    div.textContent = content;
    output.appendChild(div);
  }
  else if (type === 'tool_use') {
    var color = '#a78bfa';
    if (['Edit','Write'].indexOf(toolName) >= 0) color = '#22c55e';
    if (toolName === 'Bash') color = '#f59e0b';
    var label = filePath || content.substring(0, 80);

    var wrapper = document.createElement('div');
    wrapper.style.cssText = 'margin:4px 0;border-left:2px solid ' + color + ';padding-left:10px;';

    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:6px;cursor:pointer;';

    var arrow = document.createElement('span');
    arrow.style.cssText = 'color:#8b8fa3;font-size:10px;';
    arrow.textContent = '\u25B6';

    var nameSpan = document.createElement('span');
    nameSpan.style.cssText = 'color:' + color + ';font-size:11px;';
    nameSpan.textContent = toolName;

    var labelSpan = document.createElement('span');
    labelSpan.style.cssText = 'color:#6b7280;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    labelSpan.textContent = label;

    header.appendChild(arrow);
    header.appendChild(nameSpan);
    header.appendChild(labelSpan);

    var detail = document.createElement('div');
    detail.style.cssText = 'display:none;background:#0d1117;border-radius:4px;padding:6px 8px;font-size:10px;'
      + 'margin-top:4px;max-height:200px;overflow:auto;white-space:pre-wrap;color:#8b8fa3;';
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
    // Find the last tool detail block and fill it
    var details = output.querySelectorAll('[data-tool-detail]');
    if (details.length) {
      var last = details[details.length - 1];
      last.textContent = content.substring(0, 500);
      last.style.display = 'block';
      // Update arrow
      var arrow = last.previousElementSibling;
      if (arrow) {
        var arrowEl = arrow.querySelector('span');
        if (arrowEl) arrowEl.textContent = '\u25BC';
      }
    }
  }
  else if (type === 'task_completed' || type === 'task_failed') {
    var clr = type === 'task_completed' ? '#22c55e' : '#f85149';
    appendBlock(output, 'div', content, {color:clr, margin:'8px 0', paddingLeft:'2px'});
    // Re-enable input — run is done
    var input = document.getElementById('agent-input');
    if (input) { input.disabled = false; input.placeholder = 'Continue the session...'; input.focus(); }
    if (_agentWs) { _agentWs.close(); _agentWs = null; }
  }
  // Skip 'result' type — its text content duplicates 'assistant' events
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
    if (!r.ok) throw new Error('Failed to close session (status ' + r.status + ')');
    _agentSessionId = null;
    var s = document.getElementById('agent-session-status');
    if (s) { s.textContent = 'no session'; s.dataset.sessionId = ''; }
    var o = document.getElementById('agent-output');
    if (o) appendBlock(o, 'div', 'Session ended.', {color:'var(--text-disabled)', margin:'12px 0', fontStyle:'italic'});
    var i = document.getElementById('agent-input');
    if (i) i.placeholder = 'Start a new session...';
  })
  .catch(function(err) {
    var o = document.getElementById('agent-output');
    if (o) appendBlock(o, 'div', 'Failed to close session: ' + err.message, {color:'#f85149', margin:'8px 0'});
  });
}

// ── DOM helpers (avoid innerHTML += which re-parses and loses event listeners) ──

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
