// WebSocket streaming helpers — per-run and global broadcast
function connectRunStream(runId, targetId) {
  var el = document.getElementById(targetId);
  if (!el) return null;
  var url = runId ? '/ws/runs/' + runId : '/ws/runs';
  var ws = new WebSocket(url);
  ws.onmessage = function(e) {
    el.textContent += e.data;
    el.scrollTop = el.scrollHeight;
  };
  ws.onerror = function() {
    el.textContent += '\n[connection error]';
  };
  return ws;
}

function connectGlobalStream(targetId) {
  return connectRunStream('', targetId);
}
