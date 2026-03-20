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

  // Render user prompt client-side
  output.innerHTML += '<div style="color:#6b7280;font-size:10px;margin-top:12px;">you</div>'
    + '<div style="color:#e0e0e0;margin-bottom:12px;padding-left:2px;">' + escapeHtml(prompt) + '</div>';
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
    output.innerHTML += '<div style="color:#3b82f6;font-size:10px;">agent</div>';
    connectAgentStream(data.run_id, output, input);
  })
  .catch(function(err) {
    output.innerHTML += '<div style="color:#f85149;margin:8px 0;">Error: ' + escapeHtml(err.message) + '</div>';
    input.disabled = false;
    input.placeholder = 'Try again...';
  });
}

function connectAgentStream(runId, output, input) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs/' + runId);
  _agentWs = ws;

  ws.onmessage = function(e) {
    var event = JSON.parse(e.data);
    renderAgentEvent(event, output);
    output.scrollTop = output.scrollHeight;
  };
  ws.onclose = function() {
    input.disabled = false;
    input.placeholder = 'Continue the session...';
    input.focus();
  };
  ws.onerror = function() {
    output.innerHTML += '<div style="color:#f85149;margin:4px 0;padding-left:2px;">[connection error]</div>';
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
    output.innerHTML += '<div style="color:#c0c4d6;margin:4px 0;padding-left:2px;white-space:pre-wrap;">'
      + escapeHtml(content) + '</div>';
  }
  else if (type === 'tool_use') {
    var color = '#a78bfa';
    if (['Edit','Write'].indexOf(toolName) >= 0) color = '#22c55e';
    if (toolName === 'Bash') color = '#f59e0b';
    var label = filePath || content.substring(0, 80);
    output.innerHTML += '<div style="margin:4px 0;border-left:2px solid ' + color + ';padding-left:10px;">'
      + '<div style="display:flex;align-items:center;gap:6px;cursor:pointer;" '
      + 'onclick="var d=this.nextElementSibling;if(d)d.style.display=d.style.display===\'none\'?\'block\':\'none\'">'
      + '<span style="color:#8b8fa3;font-size:10px;">&#9654;</span>'
      + '<span style="color:' + color + ';font-size:11px;">' + escapeHtml(toolName) + '</span>'
      + '<span style="color:#6b7280;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escapeHtml(label) + '</span>'
      + '</div>'
      + '<div style="display:none;background:#0d1117;border-radius:4px;padding:6px 8px;font-size:10px;'
      + 'margin-top:4px;max-height:200px;overflow:auto;white-space:pre-wrap;color:#8b8fa3;">'
      + escapeHtml(content) + '</div></div>';
  }
  else if (type === 'tool_result') {
    var blocks = output.querySelectorAll('[style*="border-left:2px"]');
    if (blocks.length) {
      var last = blocks[blocks.length - 1];
      var detail = last.querySelector('div[style*="display:none"], div[style*="display:block"]');
      if (detail) { detail.textContent = content.substring(0, 500); detail.style.display = 'block'; }
    }
  }
  else if (type === 'task_completed') {
    output.innerHTML += '<div style="color:#22c55e;margin:8px 0;padding-left:2px;">' + escapeHtml(content) + '</div>';
  }
  else if (type === 'task_failed') {
    output.innerHTML += '<div style="color:#f85149;margin:8px 0;padding-left:2px;">' + escapeHtml(content) + '</div>';
  }
  else if (type === 'result' && content) {
    output.innerHTML += '<div style="color:#c0c4d6;margin:4px 0;padding-left:2px;white-space:pre-wrap;">'
      + escapeHtml(content.substring(0, 1000)) + '</div>';
  }
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
  .then(function() {
    _agentSessionId = null;
    var s = document.getElementById('agent-session-status');
    if (s) { s.textContent = 'no session'; s.dataset.sessionId = ''; }
    var o = document.getElementById('agent-output');
    if (o) o.innerHTML += '<div style="color:var(--text-disabled);margin:12px 0;font-style:italic;">Session ended.</div>';
    var i = document.getElementById('agent-input');
    if (i) i.placeholder = 'Start a new session...';
  });
}

function escapeHtml(text) {
  var d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}
