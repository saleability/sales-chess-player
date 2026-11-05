"""Run: python -m unittest -v test_chesslens.py"""
import subprocess
import os
import unittest
from pathlib import Path

import chess
import chess.engine
import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from core import (PositionTracker, Recognizer, RecognitionError, SyncError, render_board, screen_cell,
                  square_at, PromotionMenu, find_board, move_instruction, choose_style)

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets" / "neo"
ENGINE = ROOT / "engine" / "stockfish" / "stockfish-windows-x86-64-universal.exe"
PROMOTION_FEN = "4k3/4n1PP/4KB2/8/1p6/1P6/8/8 w - - 0 1"


def promotion_frame(board, move, flipped=False, size=640):
    after = board.copy()
    after.push(move)
    image = render_board(after, ASSETS, size, flipped)
    row, col = screen_cell(move.to_square, flipped)
    direction = 1 if row == 0 else -1
    menu = PromotionMenu(move.to_square, board.turn, row, col, direction, flipped)
    for piece_type in (chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP):
        r, c = menu.choice_cell(piece_type)
        y0, y1 = round(r*size/8), round((r+1)*size/8)
        x0, x1 = round(c*size/8), round((c+1)*size/8)
        tile = image[y0:y1, x0:x1]
        tile[:] = 255
        name = ("w" if board.turn else "b") + chess.piece_symbol(piece_type)
        rgba = cv2.imread(str(ASSETS / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        rgba = cv2.resize(rgba, (x1-x0, y1-y0), interpolation=cv2.INTER_AREA)
        alpha = rgba[:, :, 3:4] / 255
        tile[:] = rgba[:, :, :3] * alpha + tile * (1-alpha)
    return image


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recognizer = Recognizer(ASSETS)

    def test_screens_at_different_sizes_orientations_and_highlights(self):
        board = chess.Board()
        for move in ["e2e4", "c7c5", "g1f3", "b8c6", "f1b5"]:
            board.push_uci(move)
        for size in (320, 560, 743):
            for flipped in (False, True):
                with self.subTest(size=size, flipped=flipped):
                    image = render_board(board, ASSETS, size, flipped, (chess.F1, chess.B5))
                    scan = self.recognizer.recognize(image, flipped)
                    self.assertEqual(scan.placement, board.board_fen())

    def test_all_pieces_and_colors(self):
        board = chess.Board()
        scan = self.recognizer.recognize(render_board(board, ASSETS))
        self.assertEqual(scan.placement, board.board_fen())

    def test_blank_screen_and_occluded_board_rejected(self):
        with self.assertRaises(RecognitionError):
            self.recognizer.recognize(np.zeros((640, 640, 3), np.uint8))
        image = render_board(chess.Board(), ASSETS)
        cv2.rectangle(image, (220, 0), (420, 640), (20, 30, 40), -1)
        with self.assertRaises(RecognitionError):
            self.recognizer.recognize(image)

    def test_coordinates_round_trip(self):
        for flipped in (False, True):
            for square in chess.SQUARES:
                self.assertEqual(square_at(*screen_cell(square, flipped), flipped), square)


class TrackerTests(unittest.TestCase):
    def test_initial_position_and_fast_two_ply_continuation(self):
        tracker = PositionTracker()
        board = chess.Board()
        tracker.accept(board.board_fen())
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        tracked, changed = tracker.accept(board.board_fen())
        self.assertTrue(changed)
        self.assertEqual(tracked.fen(), board.fen())

    def test_castling_en_passant_promotion_and_underpromotion(self):
        cases = [
            ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1"),
            ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2", "e5d6"),
            ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8q"),
            ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8n"),
        ]
        for fen, move in cases:
            with self.subTest(move=move):
                tracker = PositionTracker()
                board = tracker.set_fen(fen)
                board.push_uci(move)
                tracked, changed = tracker.accept(board.board_fen())
                self.assertEqual(tracked.fen(), board.fen())

    def test_repetition_keeps_game_history(self):
        tracker = PositionTracker()
        board = chess.Board()
        tracker.accept(board.board_fen())
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(move)
            tracked, _ = tracker.accept(board.board_fen())
        self.assertEqual(tracked.fen(), board.fen())
        self.assertEqual(len(tracked.move_stack), 4)

    def test_midgame_without_fen_rejected_and_invalid_fen_rejected(self):
        tracker = PositionTracker()
        board = chess.Board()
        board.push_uci("d2d4")
        with self.assertRaises(SyncError):
            tracker.accept(board.board_fen())
        with self.assertRaises(SyncError):
            tracker.set_fen("8/8/8/8/8/8/8/8 w - - 0 1")

    def test_analysis_step_back(self):
        tracker = PositionTracker()
        board = chess.Board()
        tracker.accept(board.board_fen())
        board.push_uci("e2e4")
        tracker.accept(board.board_fen())
        previous = board.copy()
        board.push_uci("e7e5")
        tracker.accept(board.board_fen())
        tracked, _ = tracker.accept(previous.board_fen())
        self.assertEqual(tracked.fen(), previous.fen())


class EngineTests(unittest.TestCase):
    def test_real_engine_finds_mate_from_recognized_screenshot(self):
        board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
        scan = Recognizer(ASSETS).recognize(render_board(board, ASSETS, 560))
        self.assertEqual(scan.placement, board.board_fen())
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW}
        with chess.engine.SimpleEngine.popen_uci(str(ENGINE), **kwargs) as engine:
            info = engine.analyse(board, chess.engine.Limit(time=.3))
            move = info["pv"][0]
            self.assertIn(move, board.legal_moves)
            board.push(move)
            self.assertTrue(board.is_checkmate(), move)

    def test_real_engine_restricts_analysis_to_detected_promotion(self):
        from app import Engine
        tracker = PositionTracker()
        tracker.set_fen(PROMOTION_FEN)
        image = promotion_frame(tracker.board, chess.Move.from_uci("g7g8q"))
        scan = Recognizer(ASSETS).recognize(image)
        board, choices = tracker.promotion_moves(scan)
        engine = Engine()
        try:
            for style in ("Balanced", "Aggressive"):
                result = engine.analyse(board, .3, style, choices)
                self.assertIn(result["pv"][0], choices)
                self.assertIn("Promote to", move_instruction(board, result["pv"][0], True)[0])
        finally:
            engine.close()


class PromotionAndLocatorTests(unittest.TestCase):
    def test_chooser_all_colors_and_orientations_and_post_promotion_sync(self):
        for black in (False, True):
            for flipped in (False, True):
                with self.subTest(black=black, flipped=flipped):
                    board = chess.Board(PROMOTION_FEN)
                    if black:
                        board = board.mirror()
                    move = chess.Move.from_uci("g2g1n" if black else "g7g8n")
                    image = promotion_frame(board, move, flipped)
                    scan = Recognizer(ASSETS).recognize(image, flipped)
                    self.assertIsNotNone(scan.promotion)
                    self.assertEqual(scan.promotion.color, board.turn)
                    self.assertEqual(scan.promotion.destination, move.to_square)
                    tracker = PositionTracker()
                    tracker.set_fen(board.fen())
                    context, choices = tracker.promotion_moves(scan)
                    self.assertEqual(context.fen(), board.fen())
                    self.assertEqual(len(choices), 4)
                    self.assertIn(move, choices)
                    board.push(move)
                    tracked, _ = tracker.accept(board.board_fen())
                    self.assertEqual(tracked.fen(), board.fen())

    def test_menu_without_context_is_identified_but_not_invented(self):
        board = chess.Board(PROMOTION_FEN)
        scan = Recognizer(ASSETS).recognize(promotion_frame(board, chess.Move.from_uci("g7g8q")))
        with self.assertRaisesRegex(SyncError, "before the pawn move"):
            PositionTracker().promotion_moves(scan)

    def test_autofind_board_with_popup_and_desktop_offset(self):
        board = chess.Board(PROMOTION_FEN)
        frame = np.full((1000, 1280, 3), 27, np.uint8)
        frame[180:820, 300:940] = promotion_frame(board, chess.Move.from_uci("g7g8q"))
        region = find_board(frame, (-1000, 50))
        self.assertEqual(region, {"left": -700, "top": 230, "width": 640, "height": 640})

    def test_no_board_rejected(self):
        with self.assertRaises(RecognitionError):
            find_board(np.zeros((900, 1200, 3), np.uint8))


class StyleTests(unittest.TestCase):
    def test_aggressive_can_prefer_capture_within_limit(self):
        board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
        lines = [{"pv": [chess.Move.from_uci(move)], "score": chess.engine.PovScore(chess.engine.Cp(score), chess.WHITE)}
                 for move, score in [("e4e5", 50), ("e4d5", 30)]]
        self.assertEqual(choose_style(board, lines, "Balanced")["pv"][0].uci(), "e4e5")
        aggressive = choose_style(board, lines, "Aggressive")
        self.assertEqual(aggressive["pv"][0].uci(), "e4d5")
        self.assertEqual(aggressive["style_loss_cp"], 20)

    def test_aggression_preserves_score_limit_and_mate(self):
        board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
        lines = [{"pv": [chess.Move.from_uci(move)], "score": chess.engine.PovScore(chess.engine.Cp(score), chess.WHITE)}
                 for move, score in [("e4e5", 100), ("e4d5", 30)]]
        self.assertEqual(choose_style(board, lines, "Aggressive")["pv"][0].uci(), "e4e5")
        lines[0]["score"] = chess.engine.PovScore(chess.engine.Mate(2), chess.WHITE)
        self.assertEqual(choose_style(board, lines, "Aggressive")["pv"][0].uci(), "e4e5")

    def test_piece_names_and_underpromotion_instructions(self):
        self.assertEqual(move_instruction(chess.Board(), chess.Move.from_uci("g1f3"))[0], "Knight to f3")
        board = chess.Board(PROMOTION_FEN)
        title, instruction = move_instruction(board, chess.Move.from_uci("g7g8n"), True)
        self.assertEqual(title, "Promote to knight")
        self.assertEqual(instruction, "Choose the knight in the promotion menu.")


class MenuFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import QApplication
        from PySide6.QtGui import QFontDatabase, QFont
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setStyle("Fusion")
        for font in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)
        cls.qt.setFont(QFont("Segoe UI", 9))

    def setUp(self):
        from app import ChessLens
        self.window = ChessLens(enable_hotkey=False)
        self.window.timer.stop()
        # Check state transitions without showing or manipulating desktop overlays.
        self.window.show_overlay = lambda: None

    def tearDown(self):
        self.window.close()

    def test_promotion_replaces_stale_advice_then_resumes_tracking(self):
        window = self.window
        window.active = True
        window.screen_trusted = True
        window.tracker.set_fen(PROMOTION_FEN)
        window.queue_analysis(window.tracker.board)
        menu = Recognizer(ASSETS).recognize(promotion_frame(window.tracker.board, chess.Move.from_uci("g7g8q")))
        window.consume_scan(menu)
        self.assertIsNone(window.pending_analysis)
        self.assertIsNone(window.last_move)
        window.consume_scan(menu)
        self.assertEqual(len(window.pending_analysis[-1]), 4)
        move = chess.Move.from_uci("g7g8n")
        window.show_result(window.tracker.board,
                           {"pv": [move], "score": chess.engine.PovScore(chess.engine.Cp(100), chess.WHITE)},
                           (window.revision, window.tracker.board.fen()))
        self.assertEqual(window.move_label.text(), "Promote to knight")
        self.assertIn("promotion menu", window.instruction.text())
        after = window.tracker.board.copy()
        after.push(move)
        normal = Recognizer(ASSETS).recognize(render_board(after, ASSETS))
        window.consume_scan(normal)
        window.consume_scan(normal)
        self.assertEqual(window.tracker.board.fen(), after.fen())
        self.assertIsNone(window.promotion)

    def test_missing_context_explains_promotion_without_recommending_a_piece(self):
        window = self.window
        menu = Recognizer(ASSETS).recognize(promotion_frame(chess.Board(PROMOTION_FEN), chess.Move.from_uci("g7g8q")))
        with self.assertRaises(SyncError):
            window.consume_scan(menu)
        self.assertEqual(window.move_label.text(), "Promotion detected")
        self.assertIsNone(window.last_move)

    def test_style_change_invalidates_old_search_and_reaches_engine_request(self):
        window = self.window
        window.active = True
        window.tracker.set_fen(chess.STARTING_FEN)
        window.queue_analysis(window.tracker.board)
        before = window.revision
        window.style.setCurrentText("Aggressive")
        self.assertGreater(window.revision, before)
        self.assertIsNone(window.pending_analysis)
        window.queue_analysis(window.tracker.board)
        self.assertEqual(window.pending_analysis[3], "Aggressive")

    def test_compact_and_expanded_menu_fit_without_horizontal_clipping(self):
        window = self.window
        window.show()
        self.qt.processEvents()
        self.assertEqual(window.centralWidget().horizontalScrollBar().maximum(), 0)
        self.assertEqual(window.centralWidget().verticalScrollBar().maximum(), 0)
        window.advanced.show()
        window.resize(430, 880)
        self.qt.processEvents()
        self.assertEqual(window.centralWidget().horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
