// ── Multimodal: image attachments, voice ──
// Depends on globals: _chatAttachments, _voiceRecognition, _voiceActive

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

// ── Push-to-talk voice ──

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
