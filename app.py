"""ChessLens: local Windows screen-reading chess analysis overlay."""
from __future__ import annotations

import ctypes
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Keep Qt selection coordinates and desktop capture pixels in the same space.
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass

import chess
import chess.engine
import cv2
import mss
import numpy as np
from PySide6.QtCore import (QAbstractNativeEventFilter, QEasingCurve, QPoint, QPointF,
                            QPropertyAnimation, QRect, QRectF, QSettings, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from core import (PositionTracker, Recognizer, RecognitionError, SyncError, render_board,
                  screen_cell, find_board, move_instruction, choose_style)

BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# In a PyInstaller one-file build, bundled data is extracted to _MEIPASS;
# the executable's directory is still used for external runtime files.
RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", BASE))
ASSETS = RESOURCE_BASE / "assets" / "neo"
ENGINE = RESOURCE_BASE / "engine" / "stockfish" / "stockfish-windows-x86-64-universal.exe"
ACCENT = QColor("#ffffff")


def pixmap_bgr(image: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy())


def draw_arrow(painter: QPainter, rect: QRectF, move: chess.Move, flipped: bool):
    step = rect.width() / 8
    r1, c1 = screen_cell(move.from_square, flipped)
    r2, c2 = screen_cell(move.to_square, flipped)
    start = QPointF(rect.left() + (c1 + .5) * step, rect.top() + (r1 + .5) * step)
    end = QPointF(rect.left() + (c2 + .5) * step, rect.top() + (r2 + .5) * step)
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    head = step * .31
    shaft_end = end - QPointF(math.cos(angle) * head * .58, math.sin(angle) * head * .58)
    painter.setPen(QPen(QColor(13, 24, 23, 130), step * .18, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(start, shaft_end)
    painter.setPen(QPen(ACCENT, step * .12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(start, shaft_end)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ACCENT)
    painter.drawPolygon(QPolygonF([
        end,
        end - QPointF(math.cos(angle - .55) * head, math.sin(angle - .55) * head),
        end - QPointF(math.cos(angle + .55) * head, math.sin(angle + .55) * head),
    ]))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(ACCENT, max(2, step * .035)))
    painter.drawEllipse(start, step * .15, step * .15)


def click_screen_point(x: int, y: int):
    """Send a left click to the selected board on Windows."""
    if sys.platform != "win32":
        raise RuntimeError("Auto-play clicks are available on Windows only.")
    user32 = ctypes.windll.user32
    if not user32.SetCursorPos(int(x), int(y)):
        raise RuntimeError("Couldn't move the pointer to the chessboard.")
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP


class MoveOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.move_hint = None
        self.flipped = False
        self.capture_excluded = False
        self.promotion = None

    def show_move(self, region: dict, move: chess.Move, flipped: bool, promotion=None):
        self.setGeometry(region["left"], region["top"], region["width"], region["height"])
        self.move_hint, self.flipped = move, flipped
        self.promotion = promotion
        self.show()
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.capture_excluded = bool(user32.SetWindowDisplayAffinity(int(self.winId()), 0x11))
        self.update()

    def paintEvent(self, event):
        if self.move_hint:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if self.promotion and self.move_hint.promotion:
                row, col = self.promotion.choice_cell(self.move_hint.promotion)
                size = self.width() / 8
                box = QRectF(col * size + 4, row * size + 4, size - 8, size - 8)
                painter.setPen(QPen(ACCENT, max(3, size * .045)))
                painter.setBrush(QColor(124, 242, 187, 30))
                painter.drawRoundedRect(box, 7, 7)
            else:
                draw_arrow(painter, QRectF(self.rect()), self.move_hint, self.flipped)


class BoardSelector(QWidget):
    selected = Signal(object)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        with mss.mss() as capture:
            bounds = capture.monitors[0]
            image = np.asarray(capture.grab(bounds))[:, :, :3].copy()
        self.setGeometry(bounds["left"], bounds["top"], bounds["width"], bounds["height"])
        self.snapshot = pixmap_bgr(image)
        self.origin = None
        self.selection = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.snapshot)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if not self.selection.isEmpty():
            path.addRect(QRectF(self.selection))
        painter.fillPath(path, QColor(5, 12, 16, 165))
        painter.setPen(QPen(ACCENT, 3))
        painter.drawRect(self.selection)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 14))
        painter.drawText(QRect(0, 30, self.width(), 70), Qt.AlignmentFlag.AlignCenter,
                         "Drag from the board's top-left to its bottom-right.\nInclude only the 64 squares.  Esc to cancel.")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            current = event.position().toPoint()
            dx, dy = current.x() - self.origin.x(), current.y() - self.origin.y()
            side = min(abs(dx), abs(dy))
            end = self.origin + QPoint(side if dx >= 0 else -side, side if dy >= 0 else -side)
            self.selection = QRect(self.origin, end).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.selection.width() >= 240:
            point = self.mapToGlobal(self.selection.topLeft())
            region = {"left": point.x(), "top": point.y(), "width": self.selection.width(), "height": self.selection.width()}
            self.close()
            self.selected.emit(region)
        else:
            self.origin = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()


class BoardPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(176, 176)
        self.board = None
        self.flipped = False
        self.move_hint = None
        self.image = None

    def set_board(self, board, flipped=False, move=None):
        self.board, self.flipped, self.move_hint = board, flipped, move
        self.image = pixmap_bgr(render_board(board, ASSETS, self.width(), flipped)) if board else None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.image:
            painter.drawPixmap(0, 0, self.image)
            if self.move_hint:
                draw_arrow(painter, QRectF(self.rect()), self.move_hint, self.flipped)
        else:
            for row in range(8):
                for col in range(8):
                    painter.fillRect(col * 22, row * 22, 22, 22, QColor("#283737" if (row+col)%2 else "#354848"))
            painter.fillRect(self.rect(), QColor(10, 18, 23, 105))
            painter.setPen(QColor("#e2eeeb"))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select your board\nto begin analysis")


class Engine:
    def __init__(self):
        self.process = None

    def analyse(self, board, seconds, style="Balanced", root_moves=None):
        if self.process is None:
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            self.process = chess.engine.SimpleEngine.popen_uci(str(ENGINE), timeout=15, **kwargs)
            self.process.configure({"Threads": min(4, max(1, (os.cpu_count() or 2) // 2)), "Hash": 128})
        try:
            count = min(3, len(root_moves)) if root_moves else 3
            lines = self.process.analyse(board, chess.engine.Limit(time=seconds),
                                        multipv=count if style in ("Aggressive", "Fastest Checkmate") else 1,
                                        root_moves=root_moves)
            return choose_style(board, lines, style)
        except Exception:
            self.process.close()
            self.process = None
            raise

    def close(self):
        if self.process:
            self.process.close()


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == 0xC1E5:
                self.callback()
                return True, 0
        return False, 0


class ChessLens(QMainWindow):
    def __init__(self, enable_hotkey=True):
        super().__init__()
        self.setWindowTitle("Sales Chess Player")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.settings = QSettings("ChessLens", "ChessLens")
        self.animations_enabled = True
        self.custom_palette = None
        self.region = None
        self.board_flipped = False
        self.active = False
        self.tracker = PositionTracker()
        self.recognizer = Recognizer(ASSETS)
        self.engine = Engine()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ChessLens")
        self.scan_future = self.analysis_future = None
        self.find_future = None
        self.promotion = None
        self.scan_revision = 0
        self.revision = 0
        self.screen_trusted = False
        self.candidate = None
        self.streak = 0
        self.last_scan = 0
        self.pending_analysis = None
        self.requested_key = self.result_key = None
        self.last_move = None
        self.auto_play_key = None
        self.overlay = MoveOverlay()
        self.selector = None
        self.demo = None
        self.build_ui()
        self.load_preferences()
        self.hotkey = HotkeyFilter(self.toggle)
        QApplication.instance().installNativeEventFilter(self.hotkey)
        self.hotkey_registered = False
        if sys.platform == "win32" and enable_hotkey:
            self.hotkey_registered = bool(ctypes.windll.user32.RegisterHotKey(None, 0xC1E5, 0x0001 | 0x0002 | 0x4000, ord("P")))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def build_ui(self):
        from ui import build_menu
        build_menu(self, BoardPreview())

    def load_preferences(self):
        values = (
            (self.theme, "theme", "Black & White"),
            (self.layout_mode, "layout", "Standard"),
            (self.style, "style", "Balanced"),
        )
        for widget, key, default in values:
            widget.blockSignals(True)
            widget.setCurrentText(str(self.settings.value(key, default)))
            widget.blockSignals(False)
        for widget, key, default in (
            (self.think, "thinkingSeconds", 2.0),
            (self.accuracy, "analysisAccuracy", 50),
            (self.accuracy_percent, "analysisAccuracy", 50),
            (self.auto_play, "autoPlay", False),
            (self.auto_flip, "autoFlip", True),
            (self.flip, "blackAtBottom", False),
        ):
            widget.blockSignals(True)
            if widget is self.think:
                widget.setValue(float(self.settings.value(key, default)))
            elif widget in (self.accuracy, self.accuracy_percent):
                stored = int(self.settings.value(key, default))
                if int(self.settings.value("analysisAccuracyVersion", 1)) < 2:
                    stored *= 10
                widget.setValue(stored)
            else:
                widget.setChecked(self.settings.value(key, default, type=bool))
            widget.blockSignals(False)
        self.accuracy_percent.setValue(self.accuracy.value())
        self.settings.setValue("analysisAccuracyVersion", 2)
        self.custom_palette = self.settings.value("customTheme", {})
        self.animations.blockSignals(True)
        self.animations.setChecked(self.settings.value("animations", True, type=bool))
        self.animations.blockSignals(False)
        self.flip.setEnabled(not self.auto_flip.isChecked())
        self.board_flipped = self.flip.isChecked() and not self.auto_flip.isChecked()
        tab_index = self.settings.value("selectedTab", 0, type=int)
        self.tab_widget.setCurrentIndex(max(0, min(tab_index, self.tab_widget.count() - 1)))
        self.apply_theme(self.theme.currentText())
        self.apply_layout_mode(self.layout_mode.currentText())
        self.set_background_image(str(self.settings.value("backgroundImage", "")), persist=False)
        self.set_animations_enabled(self.animations.isChecked())
        self.style_changed(self.style.currentText())

    def apply_theme(self, theme):
        from ui import apply_theme
        apply_theme(self, theme)
        self.settings.setValue("theme", theme)

    def apply_layout_mode(self, mode):
        from ui import apply_layout_mode
        apply_layout_mode(self, mode)
        self.settings.setValue("layout", mode)

    def save_preference(self, key, value):
        self.settings.setValue(key, value)

    def tab_changed(self, index):
        self.settings.setValue("selectedTab", index)

    def preference_snapshot(self):
        return {
            "theme": self.theme.currentText(),
            "customTheme": self.custom_palette or {},
            "backgroundImage": self.settings.value("backgroundImage", ""),
            "layout": self.layout_mode.currentText(),
            "style": self.style.currentText(),
            "thinkingSeconds": self.think.value(),
            "analysisAccuracy": self.accuracy.value(),
            "analysisAccuracyVersion": 2,
            "autoPlay": self.auto_play.isChecked(),
            "autoFlip": self.auto_flip.isChecked(),
            "blackAtBottom": self.flip.isChecked(),
            "animations": self.animations.isChecked(),
            "selectedTab": self.tab_widget.currentIndex(),
        }

    def _saved_configs(self):
        try:
            return json.loads(str(self.settings.value("profilesJson", "{}")))
        except (TypeError, ValueError):
            return {}

    def refresh_profiles(self, selected=None):
        if not hasattr(self, "profile"):
            return
        names = sorted(self._saved_configs(), key=str.casefold)
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem("Choose saved config…")
        self.profile.addItems(names)
        if selected in names:
            self.profile.setCurrentText(selected)
        self.profile.blockSignals(False)

    def save_config_dialog(self):
        name, accepted = QInputDialog.getText(self, "Save config", "Name this settings config:")
        name = name.strip()
        if not accepted or not name:
            return
        configs = self._saved_configs()
        configs[name] = self.preference_snapshot()
        self.settings.setValue("profilesJson", json.dumps(configs, ensure_ascii=False))
        self.refresh_profiles(name)
        self.status.setText(f"Saved config: {name}")

    def load_selected_config(self):
        name = self.profile.currentText()
        config = self._saved_configs().get(name)
        if not isinstance(config, dict):
            self.status.setText("Choose a saved config first.")
            return
        self.custom_palette = config.get("customTheme") or self.custom_palette
        self.settings.setValue("customTheme", self.custom_palette or {})
        for widget, key, default in (
            (self.theme, "theme", "Black & White"),
            (self.layout_mode, "layout", "Standard"),
            (self.style, "style", "Balanced"),
        ):
            widget.blockSignals(True)
            widget.setCurrentText(str(config.get(key, default)))
            widget.blockSignals(False)
        for widget, key, default in (
            (self.think, "thinkingSeconds", 2.0),
            (self.accuracy, "analysisAccuracy", 50),
            (self.accuracy_percent, "analysisAccuracy", 50),
            (self.auto_play, "autoPlay", False),
            (self.auto_flip, "autoFlip", True),
            (self.flip, "blackAtBottom", False),
            (self.animations, "animations", True),
        ):
            widget.blockSignals(True)
            if widget is self.think:
                widget.setValue(float(config.get(key, default)))
            elif widget in (self.accuracy, self.accuracy_percent):
                stored = int(config.get(key, default))
                if int(config.get("analysisAccuracyVersion", 1)) < 2:
                    stored *= 10
                widget.setValue(stored)
            else:
                widget.setChecked(bool(config.get(key, default)))
            widget.blockSignals(False)
        self.flip.setEnabled(not self.auto_flip.isChecked())
        self.accuracy_percent.setValue(self.accuracy.value())
        self.board_flipped = self.flip.isChecked() and not self.auto_flip.isChecked()
        self.tab_widget.setCurrentIndex(max(0, min(int(config.get("selectedTab", 0)), self.tab_widget.count() - 1)))
        self.apply_theme(self.theme.currentText())
        self.apply_layout_mode(self.layout_mode.currentText())
        self.set_background_image(str(config.get("backgroundImage", "")))
        self.set_animations_enabled(self.animations.isChecked())
        self.settings.setValue("style", self.style.currentText())
        self.settings.setValue("thinkingSeconds", self.think.value())
        self.settings.setValue("analysisAccuracy", self.accuracy.value())
        self.settings.setValue("analysisAccuracyVersion", 2)
        self.settings.setValue("autoPlay", self.auto_play.isChecked())
        self.settings.setValue("autoFlip", self.auto_flip.isChecked())
        self.settings.setValue("blackAtBottom", self.flip.isChecked())
        self.style_changed(self.style.currentText())
        if self.tracker.board:
            self.preview.set_board(self.tracker.board, self.board_flipped)
        self.status.setText(f"Loaded config: {name}")

    def delete_selected_config(self):
        name = self.profile.currentText()
        configs = self._saved_configs()
        if name not in configs:
            self.status.setText("Choose a saved config first.")
            return
        del configs[name]
        self.settings.setValue("profilesJson", json.dumps(configs, ensure_ascii=False))
        self.refresh_profiles()
        self.status.setText(f"Deleted config: {name}")

    def choose_background_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose background image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self.set_background_image(path)

    def set_background_image(self, path, persist=True):
        from PySide6.QtGui import QPixmap
        image = QPixmap(path) if path else QPixmap()
        if path and image.isNull():
            path = ""
        self.starfield.background_image = image
        self.starfield.update()
        if persist:
            self.settings.setValue("backgroundImage", path)
        if hasattr(self, "background_button"):
            self.background_button.setText("Change background image" if path else "Choose background image")
        if hasattr(self, "theme"):
            self.apply_theme(self.theme.currentText())

    def set_animations_enabled(self, enabled):
        self.animations_enabled = bool(enabled)
        self.starfield.animations_enabled = self.animations_enabled
        if self.animations_enabled:
            self.starfield.timer.start(50)
        else:
            self.starfield.timer.stop()
        self.starfield.update()
        self.settings.setValue("animations", self.animations_enabled)

    def play_opening_animation(self):
        if not self.animations_enabled:
            self.show()
            return
        target = QRect(self.geometry())
        start = QRect(target.x(), target.y(), target.width(), 76)
        self.setGeometry(start)
        self.show()
        self._opening_animation = QPropertyAnimation(self, b"geometry", self)
        self._opening_animation.setDuration(850)
        self._opening_animation.setStartValue(start)
        self._opening_animation.setEndValue(target)
        self._opening_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opening_animation.start()

    def invalidate(self):
        self.revision += 1
        self.screen_trusted = False
        self.pending_analysis = None
        self.requested_key = self.result_key = None
        self.last_move = None
        self.auto_play_key = None
        self.promotion = None
        self.overlay.hide()
        self.move_label.setText("Waiting for board")
        self.instruction.setText("Keep all 64 squares visible while the board is being read.")
        self.piece_icon.clear()
        self.piece_icon.setText("♞")
        self.detail.setText("Stockfish 19 · waiting for a clear position")
        self.pv_label.setText("")
        if self.tracker.board:
            self.preview.set_board(self.tracker.board, self.board_flipped)

    def pause(self):
        self.active = False
        self.start_button.setText("Start scanning")
        self.badge.setText("PAUSED")
        self.candidate, self.streak = None, 0
        self.invalidate()

    def toggle(self):
        if self.active:
            self.pause()
            self.status.setText("Paused · the screen is no longer being scanned.")
        elif self.region:
            self.invalidate()
            self.active = True
            self.start_button.setText("Pause scanning")
            self.badge.setText("SCANNING")
            self.status.setText("Scanning · waiting for two clear, matching frames…")

    def find_screen_board(self):
        if self.find_future is not None:
            return
        self.pause()
        self.select_button.setEnabled(False)
        self.status.setText("Looking for a chessboard…")
        self.hide()
        QTimer.singleShot(200, self.begin_find)

    def begin_find(self):
        self.find_future = self.pool.submit(self.locate_board)

    @staticmethod
    def locate_board():
        with mss.mss() as capture:
            bounds = capture.monitors[0]
            frame = np.asarray(capture.grab(bounds))[:, :, :3].copy()
        return find_board(frame, (bounds["left"], bounds["top"]))

    def select_board(self):
        self.pause()
        self.hide()
        QTimer.singleShot(200, self.begin_selection)

    def begin_selection(self):
        try:
            self.selector = BoardSelector()
            self.selector.selected.connect(self.region_selected)
            self.selector.cancelled.connect(self.selection_cancelled)
            self.selector.show()
            self.selector.activateWindow()
        except Exception as error:
            self.show()
            self.status.setText(f"Screen capture unavailable: {error}")

    def selection_cancelled(self):
        self.show()
        self.status.setText("Selection cancelled.")

    def region_selected(self, region):
        self.region = region
        self.start_button.setEnabled(True)
        self.show()
        self.board_label.setText(f"Board found · {region['width']} × {region['height']}")
        self.toggle()

    def orientation_changed(self):
        self.save_preference("blackAtBottom", self.flip.isChecked())
        if self.auto_flip.isChecked():
            return
        was_active = self.active
        self.pause()
        self.board_flipped = self.flip.isChecked()
        if self.tracker.board:
            self.preview.set_board(self.tracker.board, self.board_flipped)
        if was_active:
            self.toggle()

    def auto_orientation_changed(self, enabled):
        self.save_preference("autoFlip", enabled)
        self.flip.setEnabled(not enabled)
        was_active = self.active
        self.pause()
        if not enabled:
            self.board_flipped = self.flip.isChecked()
        if self.tracker.board:
            self.preview.set_board(self.tracker.board, self.board_flipped)
        if was_active:
            self.toggle()

    def auto_play_changed(self, enabled):
        self.save_preference("autoPlay", enabled)
        self.auto_play_key = None
        if enabled:
            self.status.setText("Auto-play enabled for computer practice · moves the detected color at the bottom.")
            if self.tracker.board and self.last_move and self.result_key:
                self.schedule_auto_play(self.tracker.board.copy(), self.last_move, self.result_key)
        else:
            self.status.setText("Auto-play off · make the recommended move yourself.")

    def thinking_changed(self):
        self.save_preference("thinkingSeconds", self.think.value())
        self.invalidate()
        if self.tracker.board and not self.active:
            self.queue_analysis(self.tracker.board)

    def accuracy_changed(self, value):
        source = self.sender()
        other = self.accuracy_percent if source is self.accuracy else self.accuracy
        other.blockSignals(True)
        other.setValue(value)
        other.blockSignals(False)
        self.save_preference("analysisAccuracy", value)
        self.save_preference("analysisAccuracyVersion", 2)
        self.invalidate()
        if self.tracker.board and not self.active:
            self.queue_analysis(self.tracker.board)

    def style_changed(self, style):
        self.save_preference("style", style)
        notes = {
            "Balanced": "Balanced chooses Stockfish's strongest line.",
            "Aggressive": "Prefers checks, captures and pressure among close engine choices.",
            "Fastest Checkmate": "Seeks a forced mate and favors the shortest line found. If none is found, shows the strongest line.",
        }
        self.style_note.setText(notes.get(style, notes["Balanced"]))
        self.thinking_changed()

    def reset(self):
        self.pause()
        self.tracker.reset()
        self.preview.set_board(None)
        self.status.setText("Reset · scan the starting position, or paste a full FEN.")

    def fen_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Load a chess position")
        dialog.resize(480, 220)
        layout = QVBoxLayout(dialog)
        label = QLabel("Paste the complete FEN from the analysis board.\nThis includes whose turn it is, castling rights and en passant.")
        label.setWordWrap(True)
        layout.addWidget(label)
        text = QTextEdit()
        text.setPlaceholderText(chess.STARTING_FEN)
        if self.tracker.board:
            text.setPlainText(self.tracker.board.fen())
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                fen = text.toPlainText().strip()
                if len(fen.split()) != 6:
                    raise ValueError("Paste the complete FEN (all six fields).")
                # Validate before changing the running session.
                check = PositionTracker()
                check.set_fen(fen)
                self.pause()
                board = self.tracker.set_fen(fen)
                self.preview.set_board(board, self.board_flipped)
                self.status.setText("FEN loaded · analysing. Start scanning to follow this position on screen.")
                self.queue_analysis(board)
            except ValueError as error:
                QMessageBox.warning(self, "Check the position", str(error))

    def queue_analysis(self, board, root_moves=None):
        key = (self.revision, board.fen())
        if key == self.requested_key or key == self.result_key:
            return
        self.requested_key = key
        accuracy_multiplier = 1.0 + self.accuracy.value() / 100.0
        seconds = min(30.0, self.think.value() * accuracy_multiplier)
        self.pending_analysis = (key, board.copy(), seconds, self.style.currentText(), root_moves)
        self.move_label.setText("Thinking…")
        self.instruction.setText("Comparing the promotion choices…" if root_moves else "Finding which piece to move next…")
        self.detail.setText(f"{'White' if board.turn else 'Black'} to move · {seconds:g}s search · accuracy {self.accuracy.value()}%")

    def grab_board(self, region, auto_detect, flipped, expected_board=None):
        with mss.mss() as capture:
            image = np.asarray(capture.grab(region))[:, :, :3].copy()
        if auto_detect:
            return self.recognizer.recognize_auto(image, expected_board, flipped)
        return self.recognizer.recognize(image, flipped), flipped

    def tick(self):
        import time
        if self.find_future is not None and self.find_future.done():
            future, self.find_future = self.find_future, None
            self.select_button.setEnabled(True)
            self.show()
            try:
                self.region_selected(future.result())
            except Exception as error:
                self.status.setText(str(error))
                self.badge.setText("READY")
        if self.analysis_future is not None and self.analysis_future.done():
            future, key, board = self.analysis_future, self.analysis_key, self.analysis_board
            self.analysis_future = None
            try:
                info = future.result()
                if key == (self.revision, self.tracker.board.fen() if self.tracker.board else ""):
                    self.show_result(board, info, key)
            except Exception as error:
                if key[0] == self.revision:
                    self.move_label.setText("Engine error")
                    self.detail.setText(str(error)[:180])
                    self.status.setText("Pause and resume to retry the engine.")
                    self.overlay.hide()
        if self.scan_future is not None and self.scan_future.done():
            future = self.scan_future
            self.scan_future = None
            if self.active and self.scan_revision == self.revision:
                try:
                    scan, flipped = future.result()
                    if self.auto_flip.isChecked():
                        self.set_detected_orientation(flipped)
                    self.consume_scan(scan)
                except (RecognitionError, SyncError) as error:
                    self.handle_scan_error(str(error))
                except Exception as error:
                    self.handle_scan_error(f"Capture error: {error}")
            # A discarded Future still needs its exception retrieved.
            else:
                try:
                    future.result()
                except Exception:
                    pass
        if self.pending_analysis and self.analysis_future is None:
            key, board, seconds, style, root_moves = self.pending_analysis
            self.pending_analysis = None
            self.analysis_key, self.analysis_board = key, board
            self.analysis_future = self.pool.submit(self.engine.analyse, board, seconds, style, root_moves)
        if self.active and self.region and self.scan_future is None and time.monotonic() - self.last_scan >= .32:
            self.last_scan = time.monotonic()
            self.scan_revision = self.revision
            # Older Windows builds: briefly hide our arrow while capturing the board.
            if self.overlay.isVisible() and not self.overlay.capture_excluded:
                self.overlay.hide()
                QTimer.singleShot(60, self.submit_scan)
            else:
                self.submit_scan()

    def submit_scan(self):
        if self.active and self.scan_future is None:
            self.scan_revision = self.revision
            expected = self.tracker.board.copy() if self.tracker.board else None
            self.scan_future = self.pool.submit(
                self.grab_board, dict(self.region), self.auto_flip.isChecked(), self.board_flipped, expected)

    def set_detected_orientation(self, flipped):
        self.board_flipped = flipped
        self.flip.blockSignals(True)
        self.flip.setChecked(flipped)
        self.flip.blockSignals(False)

    def schedule_auto_play(self, board, move, key):
        if (not self.auto_play.isChecked() or not self.active or not self.screen_trusted
                or not self.region or key != (self.revision, board.fen())):
            return
        bottom_color = chess.BLACK if self.board_flipped else chess.WHITE
        if board.turn != bottom_color or board.is_game_over() or self.auto_play_key == key:
            return
        self.auto_play_key = key
        QTimer.singleShot(250, lambda: self.auto_play_move(board, move, key))

    def auto_play_move(self, board, move, key):
        if (not self.auto_play.isChecked() or not self.active or not self.region
                or key != (self.revision, self.tracker.board.fen() if self.tracker.board else "")
                or self.result_key != key):
            return
        bottom_color = chess.BLACK if self.board_flipped else chess.WHITE
        if board.turn != bottom_color or move not in board.legal_moves:
            return
        side = self.region["width"] / 8

        def click_cell(row, col):
            x = self.region["left"] + round((col + .5) * side)
            y = self.region["top"] + round((row + .5) * side)
            click_screen_point(x, y)

        try:
            if self.promotion and move.promotion:
                row, col = self.promotion.choice_cell(move.promotion)
                click_cell(row, col)
            else:
                click_cell(*screen_cell(move.from_square, self.board_flipped))
                import time
                time.sleep(.12)
                click_cell(*screen_cell(move.to_square, self.board_flipped))
            self.status.setText(f"Auto-play moved {board.san(move)} · waiting for the other side.")
        except Exception as error:
            self.auto_play_key = None
            self.status.setText(f"Auto-play couldn't make the move: {error}")

    def handle_scan_error(self, message):
        if self.screen_trusted:
            self.invalidate()
        self.candidate, self.streak = None, 0
        self.overlay.hide()
        self.status.setText(message)

    def consume_scan(self, scan):
        if scan.promotion:
            return self.consume_promotion(scan)
        if self.promotion:
            self.invalidate()
            self.candidate, self.streak = None, 0
        current = self.tracker.board.board_fen() if self.tracker.board else None
        if scan.placement != current and self.screen_trusted:
            self.invalidate()
        if scan.placement == self.candidate:
            self.streak += 1
        else:
            self.candidate, self.streak = scan.placement, 1
        if self.streak < 2:
            self.overlay.hide()
            return
        board, changed = self.tracker.accept(scan.placement)
        self.screen_trusted = True
        self.preview.set_board(board, self.board_flipped, self.last_move)
        self.status.setText(f"Scanning · {'White' if board.turn else 'Black'} to move · match {scan.confidence:.0%}")
        if board.is_game_over():
            self.overlay.hide()
            self.move_label.setText("Checkmate" if board.is_checkmate() else "Draw")
            self.detail.setText(f"Position ended · {board.result()}")
            self.pv_label.setText("")
            return
        self.queue_analysis(board)
        if self.last_move and self.result_key == (self.revision, board.fen()):
            self.show_overlay()

    def consume_promotion(self, scan):
        try:
            board, root_moves = self.tracker.promotion_moves(scan)
        except SyncError:
            if self.screen_trusted:
                self.invalidate()
            self.badge.setText("PROMOTION")
            self.move_label.setText("Promotion detected")
            self.instruction.setText("Load the position before the pawn move so the engine can compare the four choices.")
            raise
        menu = scan.promotion
        fingerprint = ("promotion", menu.destination, scan.placement)
        if not self.promotion or self.promotion.destination != menu.destination:
            if self.screen_trusted:
                self.invalidate()
        if self.candidate == fingerprint:
            self.streak += 1
        else:
            self.candidate, self.streak = fingerprint, 1
            self.overlay.hide()
        if self.streak < 2:
            return
        self.promotion = menu
        self.screen_trusted = True
        self.badge.setText("PROMOTION")
        self.status.setText("Promotion menu found. Comparing queen, knight, rook and bishop.")
        self.preview.set_board(board, self.board_flipped, self.last_move)
        self.queue_analysis(board, root_moves)
        if self.last_move and self.result_key == (self.revision, board.fen()):
            self.status.setText("Promotion choice ready. Choose the highlighted piece.")
            self.show_overlay()

    def show_overlay(self):
        self.overlay.show_move(self.region, self.last_move, self.board_flipped, self.promotion)

    def show_result(self, board, info, key):
        pv = info.get("pv", [])
        if not pv:
            self.move_label.setText("No legal move")
            return
        move = pv[0]
        self.last_move = move
        self.result_key = key
        title, instruction = move_instruction(board, move, bool(self.promotion))
        self.move_label.setText(title)
        self.instruction.setText(instruction)
        piece = board.piece_at(move.from_square)
        display_piece = chess.piece_symbol(move.promotion or piece.piece_type)
        path = ASSETS / f"{'w' if piece.color else 'b'}{display_piece}.png"
        self.piece_icon.setPixmap(QPixmap(str(path)).scaled(54, 54, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        score = info.get("score")
        white_score = score.white() if score else None
        if white_score is None:
            evaluation = "—"
        elif white_score.is_mate():
            mate = white_score.mate()
            evaluation = f"{'White' if mate >= 0 else 'Black'} mates in {abs(mate)}"
        else:
            evaluation = f"{white_score.score() / 100:+.2f} (White)"
        self.detail.setText(f"{board.san(move)}  ·  {evaluation}  ·  Depth {info.get('depth', '—')}")
        line_board, notation = board.copy(), []
        for step in pv[:8]:
            if step not in line_board.legal_moves:
                break
            notation.append(line_board.san(step))
            line_board.push(step)
        if info.get("style") == "Aggressive":
            explanation = f"Aggressive choice · {info.get('style_loss_cp', 0) / 100:.2f} pawns from the engine's top line.\n"
        elif info.get("style") == "Fastest Checkmate":
            side_score = score.pov(board.turn) if score else None
            mate = side_score.mate() if side_score and side_score.is_mate() else None
            explanation = (f"Shortest forced mate found · M{mate}.\n" if mate is not None and mate > 0
                           else "No forced win found in this search · strongest line shown.\n")
        else:
            explanation = ""
        self.pv_label.setText(explanation + "Line: " + "  ".join(notation))
        self.preview.set_board(board, self.board_flipped, move)
        if self.active and self.screen_trusted and self.region:
            self.show_overlay()
            self.schedule_auto_play(board, move, key)

    def open_demo(self):
        self.pause()
        if self.demo is None:
            self.demo = DemoBoard(self)
        self.demo.show()
        self.demo.raise_()
        self.status.setText("Demo opened · select its board, then start scanning.")

    def closeEvent(self, event):
        self.pause()
        self.timer.stop()
        if self.selector:
            self.selector.close()
        if self.demo:
            self.demo.close()
        if self.hotkey_registered:
            ctypes.windll.user32.UnregisterHotKey(None, 0xC1E5)
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.engine.close()
        self.overlay.close()
        event.accept()


class DemoCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(560, 560)
        self.board = chess.Board()

    def paintEvent(self, event):
        QPainter(self).drawPixmap(0, 0, pixmap_bgr(render_board(self.board, ASSETS, 560)))


class DemoBoard(QWidget):
    def __init__(self, parent):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Sales Chess Player · Demo")
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        label = QLabel("Local test board · Select just the squares below")
        label.setStyleSheet("font: 14px 'Segoe UI';")
        layout.addWidget(label)
        self.canvas = DemoCanvas()
        layout.addWidget(self.canvas)
        row = QHBoxLayout()
        for text, handler in [("Play e4", self.play_e4), ("Play …e5", self.play_e5), ("Start over", self.restart)]:
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self.setFixedSize(self.sizeHint())
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(max(screen.left(), parent.x() - 640), screen.top() + 55)

    def play_e4(self):
        self.play("e2e4")

    def play_e5(self):
        self.play("e7e5")

    def play(self, uci):
        move = chess.Move.from_uci(uci)
        if move in self.canvas.board.legal_moves:
            self.canvas.board.push(move)
            self.canvas.update()

    def restart(self):
        self.canvas.board.reset()
        self.canvas.update()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sales Chess Player")
    app.setStyle("Fusion")
    icon = QPixmap(64, 64)
    icon.fill(QColor("#000000"))
    painter = QPainter(icon)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI Symbol", 42))
    painter.drawText(icon.rect(), Qt.AlignmentFlag.AlignCenter, "♞")
    painter.end()
    app.setWindowIcon(QIcon(icon))
    window = ChessLens()
    screen = app.primaryScreen().availableGeometry()
    window.move(screen.right() - window.width() - 24, screen.top() + 28)
    window.play_opening_animation()
    return app.exec()


def self_test(report_path):
    """Verify a packaged installation without opening windows or capturing pixels."""
    board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
    scan = Recognizer(ASSETS).recognize(render_board(board, ASSETS, 560))
    if scan.placement != board.board_fen():
        raise RuntimeError("Packaged recognition check failed")
    engine = Engine()
    try:
        info = engine.analyse(board, .3)
        move = info["pv"][0]
        notation = board.san(move)
        board.push(move)
        if not board.is_checkmate():
            raise RuntimeError("Packaged engine check failed")
        import ui
        reference = render_board(chess.Board(), ASSETS, 560)
        located = find_board(reference)
        if located["width"] != 560:
            raise RuntimeError("Packaged board finder check failed")
        before = chess.Board("4k3/4n1PP/4KB2/8/1p6/1P6/8/8 w - - 0 1")
        after = before.copy()
        after.push_uci("g7g8q")
        popup = render_board(after, ASSETS, 640)
        for row, symbol in enumerate("qnrb"):
            tile = popup[row*80:(row+1)*80, 480:560]
            rgba = cv2.imread(str(ASSETS / f"w{symbol}.png"), cv2.IMREAD_UNCHANGED)
            rgba = cv2.resize(rgba, (80, 80))
            alpha = rgba[:, :, 3:4] / 255
            tile[:] = rgba[:, :, :3] * alpha + 255 * (1-alpha)
        scan = Recognizer(ASSETS).recognize(popup)
        if scan.promotion is None:
            raise RuntimeError("Packaged promotion detector check failed")
        tracker = PositionTracker()
        tracker.set_fen(before.fen())
        context, choices = tracker.promotion_moves(scan)
        for style in ("Balanced", "Aggressive", "Fastest Checkmate"):
            choice = engine.analyse(context, .2, style, choices)["pv"][0]
            if choice not in choices:
                raise RuntimeError("Packaged promotion analysis check failed")
        report = {"ok": True, "recognition": "passed", "stockfish": "passed",
                  "board_finder": "passed", "promotion_menu": "passed", "playing_styles": "passed",
                  "mate_in_one": notation, "frozen": bool(getattr(sys, "frozen", False))}
        Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(self_test(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--self-test" else main())
    except Exception:
        import traceback
        error = traceback.format_exc()
        if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
            Path(sys.argv[2]).write_text(json.dumps({"ok": False, "error": error}, indent=2), encoding="utf-8")
        elif sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, error[-2000:], "Sales Chess Player couldn't start", 0x10)
        else:
            print(error, file=sys.stderr)
        sys.exit(1)
