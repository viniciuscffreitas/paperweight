// ── Hub panel tabs ──
function activateTab(btn) {
  var tabs = btn.closest('div').querySelectorAll('button');
  tabs.forEach(function(t) {
    t.style.color = 'var(--text-muted)';
    t.style.borderBottomColor = 'transparent';
    t.removeAttribute('data-active');
  });
  btn.style.color = 'var(--text-primary)';
  btn.style.borderBottomColor = 'var(--accent)';
  btn.setAttribute('data-active', 'true');
}

// ── Hub panel (right panel / bottom sheet) ──
function openPanel() {
  var p = document.getElementById('right-panel');
  if (window.innerWidth < 768) {
    p.style.display = 'flex';
    requestAnimationFrame(function() {
      requestAnimationFrame(function() {
        p.classList.add('sheet-open');
        document.getElementById('panel-backdrop').classList.add('panel-open');
        p.setAttribute('aria-hidden', 'false');
      });
    });
  } else {
    p.style.display = 'flex';
    p.style.left = '160px';
    p.setAttribute('aria-hidden', 'false');
  }
}

function closePanel() {
  var p = document.getElementById('right-panel');
  if (window.innerWidth < 768) {
    p.classList.remove('sheet-open');
    p.style.transform = '';
    document.getElementById('panel-backdrop').classList.remove('panel-open');
    p.setAttribute('aria-hidden', 'true');
    p.addEventListener('transitionend', function handler() {
      p.style.display = 'none';
      p.removeEventListener('transitionend', handler);
    });
  } else {
    p.style.display = 'none';
    p.setAttribute('aria-hidden', 'true');
  }
}

// ── Sidebar drawer ──
function toggleSidebar() {
  var s = document.getElementById('sidebar');
  var b = document.getElementById('sidebar-backdrop');
  var isOpen = s.classList.toggle('sidebar-open');
  b.classList.toggle('sidebar-open');
  document.querySelectorAll('[aria-controls="sidebar"]').forEach(function(btn) {
    btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  });
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('sidebar-open');
  document.getElementById('sidebar-backdrop').classList.remove('sidebar-open');
  document.querySelectorAll('[aria-controls="sidebar"]').forEach(function(btn) {
    btn.setAttribute('aria-expanded', 'false');
  });
}

// ── Projects sheet ──
function openProjectsSheet() {
  var s = document.getElementById('projects-sheet');
  s.style.display = 'flex';
  requestAnimationFrame(function() {
    requestAnimationFrame(function() {
      s.classList.add('sheet-open');
      document.getElementById('projects-backdrop').classList.add('panel-open');
      s.setAttribute('aria-hidden', 'false');
    });
  });
}

function closeProjectsSheet() {
  var s = document.getElementById('projects-sheet');
  s.classList.remove('sheet-open');
  s.style.transform = '';
  document.getElementById('projects-backdrop').classList.remove('panel-open');
  s.setAttribute('aria-hidden', 'true');
  s.addEventListener('transitionend', function handler() {
    s.style.display = 'none';
    s.removeEventListener('transitionend', handler);
  });
}

// ── Swipe-to-close factory ──
function _makeSwipeable(handleId, elementId, closeFn) {
  var handle = document.getElementById(handleId);
  var el = document.getElementById(elementId);
  if (!handle || !el) return;
  var startY = 0, currentY = 0, dragging = false;
  handle.addEventListener('touchstart', function(e) {
    startY = currentY = e.touches[0].clientY; dragging = true;
    el.style.transition = 'none';
  }, { passive: true });
  handle.addEventListener('touchmove', function(e) {
    if (!dragging) return;
    currentY = e.touches[0].clientY;
    var delta = Math.max(0, currentY - startY);
    el.style.transform = 'translateY(' + delta + 'px)';
  }, { passive: true });
  handle.addEventListener('touchend', function() {
    dragging = false; el.style.transition = '';
    if ((currentY - startY) > 80) { closeFn(); }
    else { el.style.transform = ''; }
    startY = 0; currentY = 0;
  });
}

document.addEventListener('DOMContentLoaded', function() {
  _makeSwipeable('sheet-handle', 'right-panel', closePanel);
  _makeSwipeable('projects-sheet-handle', 'projects-sheet', closeProjectsSheet);
});

// ── Close all on Escape ──
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closePanel();
    closeSidebar();
    closeProjectsSheet();
  }
});
