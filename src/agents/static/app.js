// ── App: layout, navigation, sidebar ──

/* Sidebar (mobile) */
function toggleSidebar() {
  var sidebar = document.getElementById('sidebar');
  var backdrop = document.getElementById('sidebar-backdrop');
  var btn = document.querySelector('[aria-controls="sidebar"]');
  var isOpen = sidebar.classList.contains('open');
  sidebar.classList.toggle('open');
  backdrop.classList.toggle('open');
  if (btn) btn.setAttribute('aria-expanded', !isOpen);
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-backdrop').classList.remove('open');
  var btn = document.querySelector('[aria-controls="sidebar"]');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

/* Projects sheet (mobile) */
function openProjectsSheet() {
  var sheet = document.getElementById('projects-sheet');
  var backdrop = document.getElementById('projects-backdrop');
  sheet.style.display = 'flex';
  backdrop.style.display = 'block';
  requestAnimationFrame(function() {
    sheet.style.transform = 'translateY(0)';
  });
}

function closeProjectsSheet() {
  var sheet = document.getElementById('projects-sheet');
  var backdrop = document.getElementById('projects-backdrop');
  sheet.style.transform = 'translateY(110%)';
  backdrop.style.display = 'none';
  setTimeout(function() { sheet.style.display = 'none'; }, 350);
}

/* Keyboard navigation */
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    closeSidebar();
    closeProjectsSheet();
    // Close wizard if open
    var wizard = document.getElementById('wizard-overlay');
    if (wizard && wizard.style.display === 'flex') closeWizard();
  }
});

/* HTMX: re-init after swaps */
document.body.addEventListener('htmx:afterSwap', function() {
  // Scroll to top of content on navigation
  var inner = document.getElementById('content-inner');
  if (inner) inner.scrollTop = 0;
});
