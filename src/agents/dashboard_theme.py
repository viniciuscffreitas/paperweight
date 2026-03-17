"""Shared dark theme CSS and helpers for all dashboard pages."""

from nicegui import ui

DASHBOARD_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet">
<style>
html, body { margin: 0 !important; padding: 0 !important; overflow: hidden; }
body { background: #0a0c14 !important; font-family: 'JetBrains Mono', monospace; }
.nicegui-content { padding: 0 !important; margin: 0 !important; }
.q-page, .q-page-container { padding: 0 !important; margin: 0 !important; min-height: 0 !important; }
.header-row {
    background: #1a1d27 !important;
    border-bottom: 1px solid #2d3142;
    min-height: 48px;
}
.header-divider {
    width: 1px; height: 20px; background: #2d3142;
}
.status-dot {
    display: inline-block; width: 6px; height: 6px;
    border-radius: 50%; flex-shrink: 0;
}
.status-dot.running, .status-dot.active { background: #3b82f6; }
.status-dot.success { background: #4ade80; }
.status-dot.failure, .status-dot.failed { background: #f87171; }
.status-dot.timeout { background: #fb923c; }
.status-dot.cancelled { background: #6b7280; }
.panel-divider {
    width: 1px; background: #2d3142; flex-shrink: 0;
}
.section-label {
    font-size: 9px; color: #6b7280; text-transform: uppercase;
    letter-spacing: 1px; padding: 8px 12px;
    border-bottom: 1px solid #1e2130;
}
.q-table { background: transparent !important; }
.q-table thead tr th {
    background: #0f1117 !important; color: #6b7280 !important;
    font-size: 11px; font-family: 'JetBrains Mono', monospace;
}
.q-table tbody tr { cursor: pointer; }
.q-table tbody tr:hover td { background: #1e2130 !important; }
.run-drawer .q-dialog__inner {
    margin: 0 !important;
    max-height: 100vh !important; height: 100vh !important;
    width: 560px !important; max-width: 560px !important;
    border-radius: 0 !important;
}
.run-drawer .q-card {
    border-radius: 0 !important; height: 100% !important;
    background: #0d0f18 !important;
    border-left: 1px solid #2d3142 !important;
    box-shadow: -8px 0 32px rgba(0,0,0,0.6) !important;
}
@keyframes live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.live-pulse { animation: live-pulse 1.4s ease-in-out infinite; }
.trigger-menu .q-card {
    background: #1a1d27 !important;
    border: 1px solid #2d3142 !important;
}

/* ── Bottom Sheet ──────────────────────────────────────────── */
.bottom-sheet .q-dialog__inner {
    width: 100% !important; max-width: 100% !important;
    height: 82vh !important; max-height: 82vh !important;
    margin: 0 !important;
    border-radius: 14px 14px 0 0 !important;
    background: #0d0f18 !important;
    border: 1px solid #2d3142 !important;
    border-bottom: none !important;
    box-shadow: 0 -24px 64px rgba(0,0,0,0.7) !important;
    overflow: hidden !important;
    display: flex !important; flex-direction: column !important;
    white-space: nowrap;
}
.bottom-sheet .q-card {
    border-radius: 0 !important; background: transparent !important;
    box-shadow: none !important; height: 100% !important;
    width: 100% !important; max-width: 100% !important;
    display: flex !important; flex-direction: column !important;
    overflow: hidden !important;
}
@keyframes sheet-up {
    from { transform: translateY(100%); }
    to   { transform: translateY(0); }
}
.sheet-handle {
    width: 36px; height: 4px;
    background: #2d3142; border-radius: 2px;
    margin: 12px auto 0; flex-shrink: 0;
}
.step-track {
    display: flex; align-items: center;
    padding: 20px 32px; flex-shrink: 0;
}
.step-item {
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px; color: #4b5563;
    text-transform: uppercase; white-space: nowrap;
}
.step-item.active { color: #e5e7eb; }
.step-item.done   { color: #3b82f6; }
.step-num {
    width: 20px; height: 20px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 600; flex-shrink: 0;
    border: 1px solid #2d3142; background: transparent; color: #4b5563;
}
.step-item.active .step-num { border-color: #e5e7eb; color: #e5e7eb; background: #1e2130; }
.step-item.done   .step-num { border-color: #3b82f6; color: #3b82f6; background: #1a2744; }
.step-connector {
    flex: 1; height: 1px; background: #1e2130;
    min-width: 24px; max-width: 48px; margin: 0 8px;
}

/* ── Right Panel ───────────────────────────────────────────── */
.right-panel .q-dialog__inner {
    width: calc(100vw - 160px) !important; max-width: calc(100vw - 160px) !important;
    min-width: 480px !important;
    height: 100vh !important; max-height: 100vh !important;
    margin: 0 !important;
    border-radius: 0 !important;
    background: #0d0f18 !important;
    border-left: 1px solid #2d3142 !important;
    box-shadow: -16px 0 48px rgba(0,0,0,0.6) !important;
    overflow: hidden !important;
    display: flex !important; flex-direction: column !important;
}
.right-panel .q-card {
    border-radius: 0 !important; background: transparent !important;
    box-shadow: none !important; height: 100% !important;
    width: 100% !important;
    display: flex !important; flex-direction: column !important;
}
@keyframes panel-in {
    from { transform: translateX(100%); }
    to   { transform: translateX(0); }
}
.panel-tabs {
    display: flex; border-bottom: 1px solid #1e2130;
    padding: 0 20px; flex-shrink: 0;
}
.panel-tab {
    padding: 10px 16px; font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase; letter-spacing: 0.8px;
    color: #4b5563; cursor: pointer;
    border: none; background: transparent;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px; transition: color 0.15s, border-color 0.15s;
}
.panel-tab:hover  { color: #9ca3af; }
.panel-tab.active { color: #e5e7eb; border-bottom-color: #3b82f6; }

/* ── Shared backdrop ───────────────────────────────────────── */
.bottom-sheet .q-dialog__backdrop,
.right-panel  .q-dialog__backdrop {
    background: rgba(0,0,0,0.55) !important;
    backdrop-filter: blur(2px) !important;
}
</style>
<script>
(function () {
  // Quasar does not reliably forward content-style to the inner wrapper.
  // Force right-panel width via MutationObserver so it always fills
  // the content area (full viewport minus 160px sidebar).
  function applyPanelWidth() {
    var inner = document.querySelector('.q-dialog.right-panel .q-dialog__inner');
    if (!inner) return;
    inner.style.setProperty('width', 'calc(100vw - 160px)', 'important');
    inner.style.setProperty('max-width', 'calc(100vw - 160px)', 'important');
    inner.style.setProperty('align-items', 'stretch', 'important');
  }
  var obs = new MutationObserver(applyPanelWidth);
  document.addEventListener('DOMContentLoaded', function () {
    obs.observe(document.body, { childList: true, subtree: true });
  });
})();
</script>
"""


def apply_dark_theme() -> None:
    """Apply dark mode and inject shared CSS. Call at top of every page handler."""
    ui.dark_mode(True)
    ui.add_head_html(DASHBOARD_CSS)
