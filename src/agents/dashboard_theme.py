"""Shared dark theme CSS and helpers for all dashboard pages."""

from nicegui import ui

DASHBOARD_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet">
<style>
body { background: #0f1117 !important; font-family: 'JetBrains Mono', monospace; }
.nicegui-content { padding: 0 !important; }
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
    position: fixed !important;
    right: 0 !important; top: 0 !important; bottom: 0 !important;
    margin: 0 !important;
    max-height: 100vh !important; height: 100vh !important;
    width: 560px !important; max-width: 560px !important;
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
</style>
"""


def apply_dark_theme() -> None:
    """Apply dark mode and inject shared CSS. Call at top of every page handler."""
    ui.dark_mode(True)
    ui.add_head_html(DASHBOARD_CSS)
