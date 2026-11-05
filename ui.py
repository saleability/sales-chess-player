"""Compact menu for ChessLens; analysis and capture stay in app.py."""
import math
import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QSlider,
    QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl


PALETTES = {
    "Black & White": {
        "background": "#000000", "panel": "#171717", "border": "#4a4a4a",
        "text": "#ffffff", "muted": "#c0c0c0", "control": "#181818",
        "hover": "#303030", "accent": "#ffffff", "accent_text": "#000000",
        "star": "#ffffff", "status": "#171717",
    },
    "White & Black": {
        "background": "#f4f4f4", "panel": "#ffffff", "border": "#c8c8c8",
        "text": "#111111", "muted": "#555555", "control": "#eeeeee",
        "hover": "#dddddd", "accent": "#111111", "accent_text": "#ffffff",
        "star": "#555555", "status": "#ffffff",
    },
    "Slate": {
        "background": "#151922", "panel": "#202632", "border": "#465064",
        "text": "#f3f5f9", "muted": "#bac2d1", "control": "#252d3a",
        "hover": "#354052", "accent": "#d8e2ff", "accent_text": "#172033",
        "star": "#d8e2ff", "status": "#202632",
    },
    "Ocean": {
        "background": "#071923", "panel": "#102b39", "border": "#286074",
        "text": "#e8f8ff", "muted": "#a6cfdd", "control": "#123544",
        "hover": "#20536a", "accent": "#64d8e8", "accent_text": "#05212a",
        "star": "#80eaff", "status": "#102b39",
    },
    "Emerald": {
        "background": "#081a13", "panel": "#11291f", "border": "#315b46",
        "text": "#effff5", "muted": "#b2d2bf", "control": "#183627",
        "hover": "#28543c", "accent": "#7ee0a2", "accent_text": "#102719",
        "star": "#9af0b8", "status": "#11291f",
    },
    "Sunset": {
        "background": "#211317", "panel": "#352025", "border": "#70404a",
        "text": "#fff3ed", "muted": "#e3bdaf", "control": "#41272d",
        "hover": "#61363d", "accent": "#ffb080", "accent_text": "#34180e",
        "star": "#ffd4a8", "status": "#352025",
    },
    "Violet": {
        "background": "#171222", "panel": "#261c36", "border": "#51416b",
        "text": "#f7f0ff", "muted": "#c9bbdf", "control": "#302443",
        "hover": "#493465", "accent": "#c4a4ff", "accent_text": "#211637",
        "star": "#decaff", "status": "#261c36",
    },
}


class AppButton(QPushButton):
    """Button subclass used for the menu's optional image-aware styling."""


class StarfieldWidget(QWidget):
    """Black canvas with a quiet, slowly drifting star field."""

    def __init__(self, parent=None):
        super().__init__(parent)
        randomizer = random.Random(23)
        self.stars = [(randomizer.random(), randomizer.random(), randomizer.uniform(.8, 2.0),
                       randomizer.random() * math.tau, randomizer.uniform(.002, .009))
                      for _ in range(92)]
        self.started = time.monotonic()
        self.background_color = QColor("#000000")
        self.star_color = QColor("#ffffff")
        self.background_image = QPixmap()
        self.animations_enabled = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.background_image.isNull():
            image = self.background_image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                 Qt.TransformationMode.SmoothTransformation)
            x = (image.width() - self.width()) // 2
            y = (image.height() - self.height()) // 2
            painter.drawPixmap(0, 0, image, x, y, self.width(), self.height())
            tint = QColor(self.background_color)
            tint.setAlpha(145)
            painter.fillRect(self.rect(), tint)
        else:
            painter.fillRect(self.rect(), self.background_color)
        if not self.animations_enabled:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        elapsed = time.monotonic() - self.started
        height = max(1, self.height())
        width = max(1, self.width())
        for x, y, radius, phase, speed in self.stars:
            progress = elapsed * speed
            star_y = ((y + progress) % 1.0) * height
            brightness = .5 + .5 * math.sin(elapsed * 1.8 + phase)
            alpha = 24 + int(brightness * 92)
            painter.setBrush(QColor(self.star_color.red(), self.star_color.green(), self.star_color.blue(), alpha))
            painter.drawEllipse(int(x * width), int(star_y), int(radius * 2), int(radius * 2))
            if brightness > .94:
                painter.setPen(QPen(QColor(self.star_color.red(), self.star_color.green(), self.star_color.blue(), min(155, alpha + 25)), 1))
                painter.drawLine(int(x * width - 3), int(star_y + radius), int(x * width + 3), int(star_y + radius))
                painter.setPen(Qt.PenStyle.NoPen)


def build_menu(window, preview):
    content = StarfieldWidget()
    window.setCentralWidget(content)
    root = QVBoxLayout(content)
    root.setContentsMargins(18, 18, 18, 16)
    root.setSpacing(12)

    header = QHBoxLayout()
    title = QLabel("♞  Sales Chess Player")
    title.setObjectName("title")
    header.addWidget(title)
    header.addStretch()
    window.discord_button = AppButton("Join Discord")
    window.discord_button.setObjectName("discord")
    window.discord_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/rMkAf7tW9e")))
    header.addWidget(window.discord_button)
    window.badge = QLabel("READY")
    window.badge.setObjectName("badge")
    header.addWidget(window.badge)
    root.addLayout(header)

    tabs = QTabWidget()
    tabs.setDocumentMode(True)
    root.addWidget(tabs, 1)
    window.tab_widget = tabs
    window.page_layouts = []

    def new_page(name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(10, 12, 10, 12)
        page_layout.setSpacing(13)
        page_layout.addStretch()
        scroll.setWidget(page)
        tabs.addTab(scroll, name)
        window.page_layouts.append(page_layout)
        return page, page_layout

    play_page, play = new_page("Play")
    board_page, board_layout = new_page("Board")
    appearance_page, appearance = new_page("Appearance")
    configs_page, configs_layout = new_page("Configs")

    hero = QFrame()
    hero.setObjectName("hero")
    hero_layout = QVBoxLayout(hero)
    hero_layout.setContentsMargins(20, 18, 20, 18)
    hero_layout.setSpacing(12)
    eyebrow = QLabel("RECOMMENDED MOVE")
    eyebrow.setObjectName("eyebrow")
    hero_layout.addWidget(eyebrow)
    main = QHBoxLayout()
    main.setSpacing(14)
    window.piece_icon = QLabel("♞")
    window.piece_icon.setObjectName("pieceIcon")
    window.piece_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.piece_icon.setFixedSize(60, 60)
    main.addWidget(window.piece_icon)
    window.move_label = QLabel("Ready to analyse")
    window.move_label.setObjectName("move")
    window.move_label.setWordWrap(True)
    main.addWidget(window.move_label, 1)
    hero_layout.addLayout(main)
    window.instruction = QLabel("Find your board to see which piece to move and where it should go.")
    window.instruction.setWordWrap(True)
    window.instruction.setObjectName("instruction")
    hero_layout.addWidget(window.instruction)
    window.detail = QLabel("Stockfish 19 · runs on your computer")
    window.detail.setObjectName("muted")
    window.detail.setWordWrap(True)
    hero_layout.addWidget(window.detail)
    play.insertWidget(0, hero)

    board_row = QHBoxLayout()
    window.board_label = QLabel("No board selected")
    window.board_label.setObjectName("muted")
    board_row.addWidget(window.board_label, 1)
    manual = AppButton("Select manually")
    manual.setObjectName("link")
    manual.clicked.connect(window.select_board)
    board_row.addWidget(manual)
    play.insertLayout(1, board_row)
    actions = QHBoxLayout()
    window.select_button = AppButton("Find board")
    window.select_button.clicked.connect(window.find_screen_board)
    actions.addWidget(window.select_button)
    window.start_button = AppButton("Start scanning")
    window.start_button.setObjectName("primary")
    window.start_button.setEnabled(False)
    window.start_button.clicked.connect(window.toggle)
    actions.addWidget(window.start_button)
    play.insertLayout(2, actions)

    style_row = QHBoxLayout()
    style_row.addWidget(QLabel("Playing style"))
    style_row.addStretch()
    window.style = QComboBox()
    window.style.addItems(["Balanced", "Aggressive", "Fastest Checkmate"])
    window.style.setMinimumWidth(185)
    window.style.currentTextChanged.connect(window.style_changed)
    style_row.addWidget(window.style)
    play.insertLayout(3, style_row)
    window.style_note = QLabel("Balanced chooses the engine's strongest line.")
    window.style_note.setObjectName("muted")
    window.style_note.setWordWrap(True)
    play.insertWidget(4, window.style_note)
    window.play_detail = window.detail

    accuracy_row = QHBoxLayout()
    accuracy_row.addWidget(QLabel("Analysis accuracy"))
    window.accuracy = QSlider(Qt.Orientation.Horizontal)
    window.accuracy.setRange(0, 100)
    window.accuracy.setSingleStep(1)
    window.accuracy.setPageStep(5)
    window.accuracy.setTracking(True)
    window.accuracy.setValue(50)
    window.accuracy.setToolTip("More time lets Stockfish search deeper. It always chooses its strongest evaluated move.")
    window.accuracy.valueChanged.connect(window.accuracy_changed)
    accuracy_row.addWidget(window.accuracy, 1)
    window.accuracy_percent = QSpinBox()
    window.accuracy_percent.setRange(0, 100)
    window.accuracy_percent.setSuffix("%")
    window.accuracy_percent.setToolTip("Type an accuracy value from 0 to 100.")
    window.accuracy_percent.valueChanged.connect(window.accuracy_changed)
    accuracy_row.addWidget(window.accuracy_percent)
    play.insertLayout(5, accuracy_row)
    window.accuracy_note = QLabel("More analysis time · strongest move selected")
    window.accuracy_note.setObjectName("muted")
    play.insertWidget(6, window.accuracy_note)

    theme_row = QHBoxLayout()
    theme_row.addWidget(QLabel("Theme"))
    window.theme = QComboBox()
    window.theme.addItems([*PALETTES.keys(), "Custom"])
    window.theme.currentTextChanged.connect(window.apply_theme)
    theme_row.addWidget(window.theme, 1)
    theme_row.addWidget(QLabel("Layout"))
    window.layout_mode = QComboBox()
    window.layout_mode.addItems(["Compact", "Standard", "Extended"])
    window.layout_mode.currentTextChanged.connect(window.apply_layout_mode)
    theme_row.addWidget(window.layout_mode, 1)
    appearance.insertLayout(0, theme_row)

    theme_tools = QHBoxLayout()
    window.edit_theme_button = AppButton("Edit custom colors")
    window.edit_theme_button.setObjectName("secondary")
    window.edit_theme_button.clicked.connect(lambda: edit_custom_theme(window))
    theme_tools.addWidget(window.edit_theme_button)
    appearance.insertLayout(1, theme_tools)
    background_tools = QHBoxLayout()
    window.background_button = AppButton("Choose background image")
    window.background_button.setObjectName("secondary")
    window.background_button.clicked.connect(window.choose_background_image)
    background_tools.addWidget(window.background_button, 1)
    window.clear_background_button = AppButton("Clear")
    window.clear_background_button.setObjectName("secondary")
    window.clear_background_button.clicked.connect(lambda: window.set_background_image(""))
    background_tools.addWidget(window.clear_background_button)
    appearance.insertLayout(2, background_tools)
    window.animations = QCheckBox("Enable background and opening animations")
    window.animations.toggled.connect(window.set_animations_enabled)
    appearance.insertWidget(3, window.animations)

    profile_row = QHBoxLayout()
    profile_row.addWidget(QLabel("Saved config"))
    window.profile = QComboBox()
    window.profile.setMinimumWidth(90)
    window.profile.addItem("Choose saved config…")
    window.refresh_profiles()
    profile_row.addWidget(window.profile, 1)
    for text, callback in (("Save", window.save_config_dialog),
                           ("Load", window.load_selected_config),
                           ("Delete", window.delete_selected_config)):
        button = AppButton(text)
        button.setObjectName("secondary")
        button.clicked.connect(callback)
        profile_row.addWidget(button)
    configs_layout.insertLayout(0, profile_row)
    window.settings_hint = QLabel("Settings save automatically. Save a named config to keep a reusable preset.")
    window.settings_hint.setObjectName("muted")
    window.settings_hint.setWordWrap(True)
    configs_layout.insertWidget(1, window.settings_hint)

    window.auto_play = QCheckBox("Auto-play moves")
    window.auto_play.setToolTip("Clicks the recommended move for the color detected at the bottom of the board.")
    window.auto_play.toggled.connect(window.auto_play_changed)
    play.insertWidget(7, window.auto_play)
    window.status = QLabel("Ready. Open an analysis or practice board, then find it.")
    window.status.setObjectName("status")
    window.status.setWordWrap(True)
    window.status.setMinimumHeight(38)
    play.insertWidget(8, window.status)

    options = QHBoxLayout()
    window.preview = preview
    options.addWidget(preview)
    controls = QVBoxLayout()
    window.auto_flip = QCheckBox("Auto-detect bottom color")
    window.auto_flip.setChecked(True)
    window.auto_flip.toggled.connect(window.auto_orientation_changed)
    controls.addWidget(window.auto_flip)
    window.flip = QCheckBox("Black at bottom")
    window.flip.setEnabled(False)
    window.flip.toggled.connect(window.orientation_changed)
    controls.addWidget(window.flip)
    controls.addWidget(QLabel("Thinking time"))
    window.think = QDoubleSpinBox()
    window.think.setRange(.2, 15)
    window.think.setSingleStep(.5)
    window.think.setDecimals(1)
    window.think.setValue(2)
    window.think.setSuffix(" seconds")
    window.think.valueChanged.connect(window.thinking_changed)
    controls.addWidget(window.think)
    controls.addStretch()
    preview_note = QLabel("Recognized position\nNeo piece set")
    preview_note.setObjectName("muted")
    controls.addWidget(preview_note)
    options.addLayout(controls)
    board_layout.insertLayout(0, options)
    tools = QHBoxLayout()
    for name, callback in [("Load FEN", window.fen_dialog), ("Reset", window.reset), ("Try demo", window.open_demo)]:
        button = AppButton(name)
        button.setObjectName("secondary")
        button.clicked.connect(callback)
        tools.addWidget(button)
    board_layout.insertLayout(1, tools)
    window.pv_label = QLabel("Engine continuation appears here.")
    window.pv_label.setObjectName("muted")
    window.pv_label.setWordWrap(True)
    board_layout.insertWidget(2, window.pv_label)
    footer = QLabel("Local analysis  ·  Ctrl+Alt+P to pause · Neo pieces")
    footer.setObjectName("footer")
    root.addWidget(footer)
    window.starfield = content
    window.menu_layout = root
    window.advanced = board_page
    window.apply_theme(window.theme.currentText())
    apply_layout_mode(window, window.layout_mode.currentText())
    tabs.currentChanged.connect(window.tab_changed)


def apply_theme(window, theme):
    palette = (getattr(window, "custom_palette", None) or PALETTES["Black & White"]
               if theme == "Custom" else PALETTES.get(theme, PALETTES["Black & White"]))
    window.starfield.background_color = QColor(palette["background"])
    window.starfield.star_color = QColor(palette["star"])
    window.starfield.update()
    stylesheet = """
        QWidget { background: transparent; color: @text@; font-family: 'Segoe UI'; font-size: 12px; }
        QLabel#title { font-size: 21px; font-weight: 700; letter-spacing: .5px; }
        QLabel#badge { padding: 5px 9px; color: @text@; background: @control@; border: 1px solid @border@; border-radius: 8px; font-size: 9px; font-weight: 700; }
        QLabel#muted { color: @muted@; font-size: 11px; }
        QLabel#brandLink { color: @muted@; font-size: 10px; }
        QScrollArea { background: transparent; }
        QTabWidget::pane { border: 1px solid @border@; border-radius: 10px; background: transparent; top: -1px; }
        QTabBar::tab { background: @control@; color: @muted@; border: 1px solid @border@; padding: 8px 12px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
        QTabBar::tab:selected { background: @panel@; color: @text@; border-bottom-color: @panel@; }
        QTabBar::tab:hover { color: @text@; }
        QFrame#hero { background: @panel@; border: 1px solid @border@; border-radius: 16px; }
        QFrame#hero QLabel { background: transparent; border: none; }
        QLabel#eyebrow { font-size: 9px; letter-spacing: 1px; font-weight: 650; color: @muted@; }
        QLabel#pieceIcon { border-radius: 12px; background: @accent@; color: @accent_text@; font-size: 40px; }
        QLabel#move { font-size: 24px; font-weight: 650; color: @text@; }
        QLabel#instruction { font-size: 13px; color: @text@; }
        QLabel#status { padding: 10px 12px; border-radius: 9px; background: @status@; border: 1px solid @border@; color: @text@; font-size: 11px; }
        QCheckBox { spacing: 8px; color: @text@; }
        QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid @border@; border-radius: 3px; background: @control@; }
        QCheckBox::indicator:checked { background: @accent@; border-color: @accent@; }
        QPushButton { background: @control@; border: 1px solid @border@; border-radius: 9px; padding: 11px; font-weight: 600; }
        QPushButton:hover { background: @hover@; }
        QPushButton:disabled { color: @muted@; background: @panel@; border-color: @border@; }
        QPushButton#primary { background: @accent@; border-color: @accent@; color: @accent_text@; }
        QPushButton#primary:hover { background: @hover@; }
        QPushButton#primary:disabled { background: @control@; border-color: @border@; color: @muted@; }
        QPushButton#link { background: transparent; border: none; padding: 2px; color: @text@; font-size: 11px; }
        QPushButton#secondary, QPushButton#discord { padding: 8px; font-size: 11px; }
        QPushButton#discord { border-radius: 7px; }
        QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit { background: @control@; border: 1px solid @border@; border-radius: 8px; padding: 8px; color: @text@; }
        QComboBox QAbstractItemView { background: @panel@; color: @text@; selection-background-color: @hover@; }
        QComboBox::drop-down { width: 24px; border: none; }
        QSlider::groove:horizontal { height: 5px; background: @border@; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: @accent@; border-radius: 2px; }
        QSlider::handle:horizontal { width: 15px; margin: -5px 0; border-radius: 7px; background: @accent@; border: 1px solid @border@; }
        QSlider::handle:horizontal:hover { background: @text@; }
        QToolButton { border: none; color: @text@; padding: 5px 0; font-size: 11px; }
        QLabel#footer { color: @muted@; font-size: 10px; }
        QScrollBar:vertical { width: 6px; background: transparent; }
        QScrollBar::handle:vertical { background: @border@; border-radius: 3px; min-height: 24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """
    for key, value in palette.items():
        stylesheet = stylesheet.replace(f"@{key}@", value)
    image_background = not window.starfield.background_image.isNull()
    if image_background:
        stylesheet += """
            QPushButton, QPushButton#primary, QPushButton#secondary, QPushButton#discord, QPushButton#link {
                background: rgba(0, 0, 0, 0); border: 1px solid rgba(255, 255, 255, 210); color: #ffffff;
            }
            QPushButton:hover, QPushButton#primary:hover, QPushButton#secondary:hover,
            QPushButton#discord:hover, QPushButton#link:hover { background: rgba(255, 255, 255, 42); }
            QPushButton:disabled, QPushButton#primary:disabled, QPushButton#secondary:disabled {
                background: rgba(0, 0, 0, 0); border-color: rgba(255, 255, 255, 90);
            }
            QTabBar::tab { background: rgba(0, 0, 0, 0); color: #ffffff; border-color: rgba(255, 255, 255, 190); }
            QTabBar::tab:selected { background: rgba(255, 255, 255, 48); color: #ffffff; border-bottom-color: rgba(255, 255, 255, 48); }
            QComboBox, QDoubleSpinBox, QSpinBox { background: rgba(0, 0, 0, 0); color: #ffffff; border-color: rgba(255, 255, 255, 200); }
            QComboBox QAbstractItemView { background: rgba(12, 12, 12, 238); color: #ffffff; }
        """
    window.setStyleSheet(stylesheet)


def edit_custom_theme(window):
    palette = dict(PALETTES["Black & White"])
    palette.update(getattr(window, "custom_palette", {}) or {})
    dialog = QDialog(window)
    dialog.setWindowTitle("Customize colors")
    dialog_layout = QVBoxLayout(dialog)
    dialog_layout.addWidget(QLabel("Choose the colors for your custom theme."))
    buttons = {}
    for key, label in (("background", "Background"), ("panel", "Cards and panels"),
                       ("border", "Borders"), ("text", "Text"), ("muted", "Secondary text"),
                       ("accent", "Accent"), ("star", "Stars")):
        row = QHBoxLayout()
        row.addWidget(QLabel(label), 1)
        button = AppButton(palette[key].upper())
        button.setStyleSheet(f"background: {palette[key]}; color: {'#000000' if QColor(palette[key]).lightness() > 128 else '#ffffff'};")
        row.addWidget(button)
        dialog_layout.addLayout(row)
        buttons[key] = button

        def choose_color(checked=False, color_key=key, color_button=button):
            selected = QColorDialog.getColor(QColor(palette[color_key]), dialog, f"Choose {color_key} color")
            if selected.isValid():
                palette[color_key] = selected.name()
                foreground = "#000000" if selected.lightness() > 128 else "#ffffff"
                color_button.setText(selected.name().upper())
                color_button.setStyleSheet(f"background: {selected.name()}; color: {foreground};")

        button.clicked.connect(choose_color)
    buttons_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    buttons_box.accepted.connect(dialog.accept)
    buttons_box.rejected.connect(dialog.reject)
    dialog_layout.addWidget(buttons_box)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    palette["control"] = palette["panel"]
    palette["status"] = palette["panel"]
    palette["hover"] = QColor(palette["panel"]).lighter(125).name()
    palette["accent_text"] = "#000000" if QColor(palette["accent"]).lightness() > 128 else "#ffffff"
    window.custom_palette = palette
    window.theme.setCurrentText("Custom")
    window.apply_theme("Custom")
    window.settings.setValue("customTheme", palette)


def apply_layout_mode(window, mode):
    if mode == "Compact":
        margins, spacing, hero_margins, hero_spacing = (16, 14, 16, 14), 9, (14, 12, 14, 12), 8
        width, height = 400, 620
        window.style_note.hide()
    elif mode == "Extended":
        margins, spacing, hero_margins, hero_spacing = (28, 26, 28, 24), 18, (22, 20, 22, 20), 14
        width, height = 480, 780
        window.style_note.show()
    else:
        margins, spacing, hero_margins, hero_spacing = (24, 24, 24, 20), 16, (20, 18, 20, 18), 12
        width, height = 430, 740
        window.style_note.show()
    window.menu_layout.setContentsMargins(14, 12, 14, 12)
    window.menu_layout.setSpacing(10)
    page_margins = (8, 8, 8, 8) if mode == "Compact" else (10, 12, 10, 12)
    for page_layout in window.page_layouts:
        page_layout.setContentsMargins(*page_margins)
        page_layout.setSpacing(spacing)
    hero_layout = window.findChild(QFrame, "hero").layout()
    hero_layout.setContentsMargins(*hero_margins)
    hero_layout.setSpacing(hero_spacing)
    window.resize(width, height)
