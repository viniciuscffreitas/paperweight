// ── WebSocket stream helpers ──

function connectRunStream(runId, onEvent, onClose, onError) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs/' + runId);

  ws.onmessage = function(e) {
    try {
      var event = JSON.parse(e.data);
      onEvent(event);
    } catch (err) {
      console.error('Stream parse error:', err);
    }
  };

  ws.onclose = function() {
    if (onClose) onClose();
  };

  ws.onerror = function() {
    if (onError) onError();
  };

  return ws;
}

function connectGlobalStream(onEvent) {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/runs');

  ws.onmessage = function(e) {
    try {
      var event = JSON.parse(e.data);
      onEvent(event);
    } catch (err) {
      console.error('Global stream parse error:', err);
    }
  };

  // Auto-reconnect
  ws.onclose = function() {
    setTimeout(function() { connectGlobalStream(onEvent); }, 5000);
  };

  return ws;
}
