"""Shared UI styling constants for the desktop app."""

APP_MIN_WIDTH = 760
APP_MIN_HEIGHT = 560
DEFAULT_COUNTDOWN_BG = "#87CEEB"

# ── Core palette ─────────────────────────────────────────────────────────
COLOR_BG_MAIN = "#0a0e17"
COLOR_BG_CARD = "#111827"
COLOR_BG_INPUT = "#0d1117"
COLOR_BG_PREVIEW = "#020617"
COLOR_BG_SUMMARY = "#0f172a"
COLOR_BG_TOOLTIP = "#1e293b"

# ── Text ─────────────────────────────────────────────────────────────────
COLOR_TEXT_TITLE = "#f1f5f9"
COLOR_TEXT_SUBTITLE = "#94a3b8"
COLOR_TEXT_INPUT = "#e2e8f0"
COLOR_TEXT_KPI = "#ffffff"

# ── Borders ──────────────────────────────────────────────────────────────
COLOR_BORDER = "#1e293b"
COLOR_BORDER_SOFT = "#334155"
COLOR_BORDER_GLOW = "#6366f1"

# ── Accent (indigo → cyan vibrant range) ─────────────────────────────────
COLOR_ACCENT = "#6366f1"
COLOR_ACCENT_HOVER = "#818cf8"
COLOR_ACCENT_PRESSED = "#4f46e5"
COLOR_ACCENT_SECONDARY = "#06b6d4"
COLOR_TEXT_ACCENT = "#f0f9ff"

# ── State colors ─────────────────────────────────────────────────────────
COLOR_DISABLED_BG = "#1e293b"
COLOR_DISABLED_TEXT = "#64748b"
COLOR_PROGRESS = "#6366f1"
COLOR_PROGRESS_CHUNK = "#22d3ee"

# ── Status indicators ───────────────────────────────────────────────────
COLOR_STATUS_INFO = "#a5b4fc"
COLOR_STATUS_ERROR = "#fca5a5"
COLOR_STATUS_AUDIO = "#67e8f9"
COLOR_STATUS_DONE = "#86efac"
COLOR_STATUS_WARN = "#fcd34d"

# ── KPI accent strip colors ─────────────────────────────────────────────
KPI_ACCENT_NEXT = "#6366f1"
KPI_ACCENT_SLIDES = "#8b5cf6"
KPI_ACCENT_IMAGES = "#06b6d4"
KPI_ACCENT_EXPORT = "#10b981"


def build_app_stylesheet() -> str:
    """Return the main application stylesheet."""
    return (
        # ── Window & containers ──────────────────────────────────────
        f"QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 {COLOR_BG_MAIN}, stop:0.5 #080d16, stop:1 #06090f); font-family: 'Segoe UI', 'Inter', 'SF Pro Display', system-ui, sans-serif; font-size: 13px; }}"
        f"QWidget#rootContainer {{ background: transparent; }}"
        f"QWidget#mainScrollViewport {{ background: transparent; }}"
        f"QWidget#scrollContent {{ background: transparent; }}"
        f"QScrollArea#mainScrollArea {{ background: transparent; border: none; }}"

        # ── Custom scrollbar ─────────────────────────────────────────
        f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}"
        f"QScrollBar::handle:vertical {{ background: rgba(99, 102, 241, 80); border-radius: 4px; min-height: 40px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: rgba(99, 102, 241, 140); }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"

        # ── Header ───────────────────────────────────────────────────
        f"QLabel#title {{ color: {COLOR_TEXT_TITLE}; font-size: 34px; font-weight: 800; padding: 14px 0 2px 0; }}"
        f"QLabel#subtitle {{ color: {COLOR_TEXT_SUBTITLE}; font-size: 14px; padding-bottom: 8px; font-weight: 400; }}"
        f"QLabel#headerBadge {{ color: rgba(99, 102, 241, 220); font-size: 11px; font-weight: 700; padding: 3px 10px; border: 1px solid rgba(99, 102, 241, 80); border-radius: 10px; }}"
        f"QLabel#hiddenWatermark {{ color: rgba(148, 163, 184, 12); font-size: 6px; letter-spacing: 0.5px; padding: 0 2px 0 0; }}"

        # ── Summary bar & KPI cards ──────────────────────────────────
        f"QFrame#summaryBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(15, 23, 42, 230), stop:1 rgba(10, 14, 23, 240)); border: 1px solid rgba(99, 102, 241, 40); border-radius: 14px; padding: 4px; }}"
        f"QFrame#kpiCard {{ background: rgba(17, 24, 39, 200); border: 1px solid rgba(255, 255, 255, 6); border-radius: 10px; }}"
        f"QFrame#kpiCardAccent {{ border-top: 3px solid {KPI_ACCENT_NEXT}; border-left: none; border-right: none; border-bottom: none; background: rgba(17, 24, 39, 200); border-radius: 10px; }}"
        f"QLabel#kpiTitle {{ color: {COLOR_TEXT_SUBTITLE}; font-size: 10px; font-weight: 700; }}"
        f"QLabel#kpiValue {{ color: {COLOR_TEXT_KPI}; font-size: 15px; font-weight: 700; }}"

        # ── Section cards ────────────────────────────────────────────
        f"QFrame#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(17, 24, 39, 250), stop:1 rgba(15, 23, 42, 250)); border: 1px solid rgba(255, 255, 255, 8); border-radius: 16px; padding: 20px; }}"
        f"QLabel#sectionTitle {{ color: {COLOR_TEXT_TITLE}; font-size: 18px; font-weight: 700; padding-bottom: 2px; }}"
        f"QLabel#sectionBody {{ color: {COLOR_TEXT_SUBTITLE}; font-size: 12px; padding-bottom: 6px; }}"
        f"QFrame#sectionSep {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(99, 102, 241, 60), stop:0.5 rgba(6, 182, 212, 40), stop:1 transparent); max-height: 1px; min-height: 1px; border: none; margin-bottom: 8px; }}"

        # ── Form labels ──────────────────────────────────────────────
        f"QLabel#fieldLabel {{ color: {COLOR_TEXT_SUBTITLE}; font-size: 12px; font-weight: 600; }}"

        # ── Checkboxes ───────────────────────────────────────────────
        f"QCheckBox {{ color: {COLOR_TEXT_INPUT}; spacing: 8px; font-size: 13px; font-weight: 500; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 2px solid {COLOR_BORDER_SOFT}; border-radius: 4px; background: {COLOR_BG_INPUT}; }}"
        f"QCheckBox::indicator:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLOR_ACCENT}, stop:1 {COLOR_ACCENT_SECONDARY}); border: 2px solid {COLOR_ACCENT}; }}"
        f"QCheckBox::indicator:hover {{ border: 2px solid {COLOR_ACCENT_HOVER}; }}"

        # ── Inputs ───────────────────────────────────────────────────
        f"QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {COLOR_BG_INPUT}; color: {COLOR_TEXT_INPUT}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 8px 12px; font-size: 13px; selection-background-color: rgba(99, 102, 241, 80); }}"
        f"QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLOR_BORDER_GLOW}; background: rgba(13, 17, 23, 255); }}"
        f"QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {COLOR_DISABLED_TEXT}; background: {COLOR_DISABLED_BG}; border: 1px solid rgba(30, 41, 59, 120); }}"
        f"QLineEdit::placeholder {{ color: {COLOR_DISABLED_TEXT}; font-style: italic; }}"

        # ── Combobox ─────────────────────────────────────────────────
        f"QComboBox {{ background: {COLOR_BG_INPUT}; color: {COLOR_TEXT_INPUT}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 8px 12px; font-size: 13px; }}"
        f"QComboBox:focus {{ border: 1px solid {COLOR_BORDER_GLOW}; }}"
        f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        f"QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {COLOR_TEXT_SUBTITLE}; margin-right: 8px; }}"
        f"QComboBox QAbstractItemView {{ background: {COLOR_BG_CARD}; color: {COLOR_TEXT_INPUT}; border: 1px solid {COLOR_BORDER_GLOW}; border-radius: 6px; selection-background-color: rgba(99, 102, 241, 100); padding: 4px; outline: none; }}"

        # ── Buttons ──────────────────────────────────────────────────
        f"QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_ACCENT}, stop:1 {COLOR_ACCENT_SECONDARY}); color: {COLOR_TEXT_ACCENT}; border: none; border-radius: 8px; padding: 9px 18px; font-weight: 700; font-size: 13px; }}"
        f"QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_ACCENT_HOVER}, stop:1 #22d3ee); }}"
        f"QPushButton:pressed {{ background: {COLOR_ACCENT_PRESSED}; padding-top: 10px; padding-bottom: 8px; }}"
        f"QPushButton:disabled {{ background: {COLOR_DISABLED_BG}; color: {COLOR_DISABLED_TEXT}; }}"
        f"QPushButton#secondaryButton {{ background: rgba(99, 102, 241, 20); color: {COLOR_STATUS_INFO}; border: 1px solid rgba(99, 102, 241, 50); }}"
        f"QPushButton#secondaryButton:hover {{ background: rgba(99, 102, 241, 40); border: 1px solid rgba(99, 102, 241, 80); }}"

        # ── Color swatch ─────────────────────────────────────────────
        f"QLabel#colorSwatch {{ border: 2px solid rgba(255, 255, 255, 15); border-radius: 8px; min-height: 30px; }}"

        # ── Preview area ─────────────────────────────────────────────
        f"QFrame#previewCard {{ background: rgba(2, 6, 23, 120); border: 1px solid {COLOR_BORDER}; border-radius: 12px; padding: 10px; }}"
        f"QPlainTextEdit#previewText {{ background: {COLOR_BG_PREVIEW}; color: {COLOR_TEXT_SUBTITLE}; border: 1px solid rgba(30, 41, 59, 100); border-radius: 8px; padding: 6px; font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace; font-size: 12px; selection-background-color: rgba(99, 102, 241, 80); }}"

        # ── Progress & status labels ─────────────────────────────────
        f"QLabel#progressLabel {{ color: {COLOR_STATUS_INFO}; font-size: 13px; padding-bottom: 2px; }}"
        f"QLabel#errorLabel {{ color: {COLOR_STATUS_ERROR}; font-size: 13px; font-weight: 600; }}"
        f"QLabel#audioStatus {{ color: {COLOR_STATUS_AUDIO}; font-size: 13px; }}"
        f"QLabel#encoderStatus {{ color: {COLOR_STATUS_INFO}; font-size: 13px; font-weight: 700; }}"

        # ── Phase status variants ────────────────────────────────────
        f"QLabel#phaseStatusInfo {{ color: {COLOR_STATUS_INFO}; font-size: 12px; font-weight: 700; }}"
        f"QLabel#phaseStatusDone {{ color: {COLOR_STATUS_DONE}; font-size: 12px; font-weight: 800; }}"
        f"QLabel#phaseStatusError {{ color: {COLOR_STATUS_ERROR}; font-size: 12px; font-weight: 800; }}"
        f"QLabel#phaseStatusWarn {{ color: {COLOR_STATUS_WARN}; font-size: 12px; font-weight: 800; }}"

        # ── Progress bar ─────────────────────────────────────────────
        f"QProgressBar {{ border: none; border-radius: 6px; background: rgba(30, 41, 59, 120); color: transparent; text-align: center; min-height: 8px; max-height: 8px; margin: 6px 0; }}"
        f"QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_ACCENT}, stop:0.6 {COLOR_ACCENT_SECONDARY}, stop:1 {COLOR_PROGRESS_CHUNK}); border-radius: 4px; }}"

        # ── Tooltips ─────────────────────────────────────────────────
        f"QToolTip {{ background: {COLOR_BG_TOOLTIP}; color: {COLOR_TEXT_INPUT}; border: 1px solid {COLOR_BORDER_GLOW}; border-radius: 6px; padding: 6px 10px; font-size: 12px; }}"

        # ── Status bar ───────────────────────────────────────────────
        f"QStatusBar {{ background: rgba(10, 14, 23, 200); color: {COLOR_TEXT_SUBTITLE}; font-size: 12px; border-top: 1px solid rgba(99, 102, 241, 30); padding: 2px 8px; }}"
        f"QStatusBar::item {{ border: none; }}"
    )
