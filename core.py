"""Screen recognition and conservative chess state tracking for ChessLens."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import cv2
import numpy as np


class RecognitionError(ValueError):
    pass


class SyncError(ValueError):
    pass


def square_at(row: int, col: int, flipped: bool = False) -> chess.Square:
    return chess.square(7 - col, row) if flipped else chess.square(col, 7 - row)


def screen_cell(square: chess.Square, flipped: bool = False) -> tuple[int, int]:
    file, rank = chess.square_file(square), chess.square_rank(square)
    return (rank, 7 - file) if flipped else (7 - rank, file)


@dataclass
class PromotionMenu:
    destination: chess.Square
    color: chess.Color
    row: int
    col: int
    direction: int
    flipped: bool = False

    @property
    def hidden(self):
        return tuple((self.row + self.direction * offset, self.col) for offset in range(5))

    def choice_cell(self, piece_type):
        offset = (chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP).index(piece_type)
        return self.row + self.direction * offset, self.col


@dataclass
class Scan:
    placement: str
    confidence: float
    image: np.ndarray
    promotion: PromotionMenu | None = None


class Recognizer:
    """Match Neo piece artwork, allowing backgrounds, highlights and small offsets.

    Only board pixels are used. A weak or ambiguous match aborts the whole scan.
    """

    def __init__(self, assets: Path):
        self.templates: dict[str, list[np.ndarray]] = {}
        for color in "wb":
            for piece in "pnbrqk":
                path = assets / f"{color}{piece}.png"
                rgba = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if rgba is None or rgba.shape[2] != 4:
                    raise RecognitionError(f"Missing piece artwork: {path.name}")
                symbol = piece.upper() if color == "w" else piece
                variants = []
                for size in (60, 64, 68):
                    scaled = cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)
                    # Uniform 72px canvas provides room for subpixel/selection offsets.
                    canvas = np.zeros((72, 72, 4), np.float32)
                    offset = (72 - size) // 2
                    canvas[offset:offset + size, offset:offset + size] = scaled / 255.0
                    variants.append(canvas)
                self.templates[symbol] = variants

    def recognize(self, image: np.ndarray, flipped: bool = False) -> Scan:
        height, width = image.shape[:2]
        if min(height, width) < 240 or abs(height - width) > 3:
            raise RecognitionError("Select a square board, at least 240 pixels wide.")
        pieces: dict[int, chess.Piece] = {}
        confidences = []
        promotion = self.find_promotion(image, flipped)
        for row in range(8):
            for col in range(8):
                if promotion and (row, col) in promotion.hidden:
                    continue
                tile = image[round(row * height / 8):round((row + 1) * height / 8),
                             round(col * width / 8):round((col + 1) * width / 8)]
                symbol, confidence = self.classify(tile)
                if symbol:
                    pieces[square_at(row, col, flipped)] = chess.Piece.from_symbol(symbol)
                    confidences.append(confidence)
        board = chess.Board(None)
        board.set_piece_map(pieces)
        if not promotion and (len(board.pieces(chess.KING, chess.WHITE)) != 1 or len(board.pieces(chess.KING, chess.BLACK)) != 1):
            raise RecognitionError("Can't see both kings. Check the board selection and Neo pieces.")
        return Scan(board.board_fen(), min(confidences, default=0), image, promotion)

    def recognize_auto(self, image: np.ndarray, expected_board: chess.Board | None = None,
                       previous_flipped: bool = False) -> tuple[Scan, bool]:
        """Recognize both board orientations and prefer the one that fits the game."""
        candidates = []
        errors = []
        for flipped in (False, True):
            try:
                scan = self.recognize(image, flipped)
            except RecognitionError as error:
                errors.append(error)
                continue
            score = self._orientation_match(scan, expected_board)
            candidates.append((score, flipped == previous_flipped, scan, flipped))
        if not candidates:
            raise errors[0] if errors else RecognitionError("Can't recognize the board orientation.")
        _, _, scan, flipped = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
        return scan, flipped

    @staticmethod
    def _orientation_match(scan: Scan, expected_board: chess.Board | None) -> int:
        if expected_board is not None:
            if scan.promotion:
                visible = chess.Board(None)
                visible.set_board_fen(scan.placement)
                menu = scan.promotion
                hidden = {square_at(row, col, menu.flipped) for row, col in menu.hidden}
                for move in expected_board.legal_moves:
                    if not move.promotion or move.to_square != menu.destination or expected_board.turn != menu.color:
                        continue
                    after = expected_board.copy()
                    after.push(move)
                    if all(after.piece_at(square) == visible.piece_at(square)
                           for square in chess.SQUARES if square not in hidden):
                        return 10000
                return -10000

            if scan.placement == expected_board.board_fen():
                return 10000
            for first in expected_board.legal_moves:
                after_first = expected_board.copy()
                after_first.push(first)
                if after_first.board_fen() == scan.placement:
                    return 8000
                for second in after_first.legal_moves:
                    after_second = after_first.copy()
                    after_second.push(second)
                    if after_second.board_fen() == scan.placement:
                        return 6000

        if scan.placement == chess.Board().board_fen():
            return 1000
        board = chess.Board(None)
        board.set_board_fen(scan.placement)
        # In ordinary positions, White's army is closer to rank one and Black's
        # is closer to rank eight. This also breaks ties before game history exists.
        score = 0
        for square, piece in board.piece_map().items():
            rank = chess.square_rank(square)
            score += (3.5 - rank) if piece.color else (rank - 3.5)
        return round(score * 10)

    def find_promotion(self, image, flipped=False):
        height, width = image.shape[:2]
        for row, direction in ((0, 1), (7, -1)):
            for col in range(8):
                destination = square_at(row, col, flipped)
                color = chess.square_rank(destination) == 7
                for offset, name in enumerate("qnrb"):
                    r = row + direction * offset
                    tile = image[round(r * height / 8):round((r + 1) * height / 8),
                                 round(col * width / 8):round((col + 1) * width / 8)]
                    # A contiguous white chooser distinguishes this from pieces
                    # coincidentally arranged down a normal board file.
                    edge = np.concatenate([tile[:max(1, len(tile)//12)].reshape(-1, 3),
                                           tile[-max(1, len(tile)//12):].reshape(-1, 3)])
                    background = np.median(edge, axis=0)
                    if background.min() < 235 or np.ptp(background) > 12:
                        break
                    try:
                        symbol, confidence = self.classify(tile)
                    except RecognitionError:
                        break
                    if symbol != (name.upper() if color else name):
                        break
                else:
                    return PromotionMenu(destination, color, row, col, direction, flipped)
        return None

    def classify(self, tile: np.ndarray) -> tuple[str | None, float]:
        tile = cv2.resize(tile[:, :, :3], (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        # Sample corners away from coordinates and piece artwork.
        background = np.median(np.concatenate([
            tile[3:8, 3:8].reshape(-1, 3), tile[3:8, 56:61].reshape(-1, 3),
            tile[56:61, 3:8].reshape(-1, 3), tile[56:61, 56:61].reshape(-1, 3)
        ]), axis=0)
        actual = tile[7:57, 7:57]
        foreground = np.max(np.abs(actual - background), axis=2) > 0.12
        coverage = float(foreground.mean())
        if coverage < 0.028:
            return None, 1.0
        scores = []
        for symbol, variants in self.templates.items():
            best = float("inf")
            for rgba in variants:
                alpha = rgba[:, :, 3:4]
                rendered = rgba[:, :, :3] * alpha + background * (1 - alpha)
                # Match the inner square, with +/- 2px translation tolerance.
                search = rendered[9:63, 9:63].astype(np.float32)
                result = cv2.matchTemplate(search, actual, cv2.TM_SQDIFF)
                error = max(0.0, float(result.min())) / actual.size
                best = min(best, error)
            scores.append((best, symbol))
        scores.sort()
        error, symbol = scores[0]
        margin = scores[1][0] - error
        if error > 0.018 or margin < 0.0015:
            raise RecognitionError("Board unclear. Use Neo pieces, remove arrows, and wait for animations.")
        return symbol, max(0, min(1, 1 - error / 0.035))


class PositionTracker:
    """Never invent turn, castling rights or en passant from an arbitrary image."""

    def __init__(self):
        self.board: chess.Board | None = None
        self.history: list[chess.Board] = []

    def set_fen(self, fen: str) -> chess.Board:
        board = chess.Board(fen.strip())
        if not board.is_valid():
            raise SyncError("This position isn't legal. Check the FEN and side to move.")
        self.board = board
        self.history = [board.copy()]
        return board.copy()

    def reset(self):
        self.board = None
        self.history = []

    def promotion_moves(self, scan: Scan) -> tuple[chess.Board, list[chess.Move]]:
        menu = scan.promotion
        if menu is None:
            raise SyncError("No promotion menu is visible.")
        if self.board is None:
            raise SyncError("Promotion menu found. Load the FEN from before the pawn move, or start scanning before promoting.")
        visible = chess.Board(None)
        visible.set_board_fen(scan.placement)
        hidden = {square_at(row, col, menu.flipped) for row, col in menu.hidden}
        moves = []
        for move in self.board.legal_moves:
            if not move.promotion or move.to_square != menu.destination or self.board.turn != menu.color:
                continue
            candidate = self.board.copy()
            candidate.push(move)
            if all(candidate.piece_at(square) == visible.piece_at(square)
                   for square in chess.SQUARES if square not in hidden):
                moves.append(move)
        if not moves or len({(move.from_square, move.to_square) for move in moves}) != 1:
            raise SyncError("Promotion menu doesn't match the tracked position. Load the FEN from before the pawn move.")
        return self.board.copy(), moves

    def accept(self, placement: str) -> tuple[chess.Board, bool]:
        if self.board is None:
            start = chess.Board()
            if placement != start.board_fen():
                raise SyncError("Midgame position: paste its full FEN to establish the turn and special rights.")
            self.board = start
            self.history = [start.copy()]
            return start.copy(), True
        if placement == self.board.board_fen():
            return self.board.copy(), False
        matches: list[chess.Board] = []
        for move in self.board.legal_moves:
            candidate = self.board.copy()
            candidate.push(move)
            if candidate.board_fen() == placement:
                matches.append(candidate)
        if len(matches) == 1:
            self.board = matches[0]
            self.history.append(self.board.copy())
            return self.board.copy(), True
        # A bot can answer between captures. Accept only a unique two-ply path.
        paths = []
        for first in self.board.legal_moves:
            intermediate = self.board.copy()
            intermediate.push(first)
            for second in intermediate.legal_moves:
                candidate = intermediate.copy()
                candidate.push(second)
                if candidate.board_fen() == placement:
                    paths.append((intermediate, candidate))
        if len(paths) == 1:
            intermediate, self.board = paths[0]
            self.history.extend([intermediate.copy(), self.board.copy()])
            return self.board.copy(), True
        # Analysis boards may step back through a game. Forward continuations
        # take precedence so repetition doesn't erase castling rights/history.
        for index in range(len(self.history) - 2, -1, -1):
            if self.history[index].board_fen() == placement:
                self.board = self.history[index].copy()
                self.history = self.history[:index + 1]
                return self.board.copy(), True
        # Don't guess a continuation after missed moves or a board edit.
        raise SyncError("Can't uniquely follow this position. Paste the current FEN or reset at the starting position.")


def render_board(board: chess.Board, assets: Path, size: int = 640,
                 flipped: bool = False, highlights: tuple[int, ...] = ()) -> np.ndarray:
    """Reference board used for repeatable integration tests and the local demo."""
    image = np.zeros((size, size, 3), np.uint8)
    for row in range(8):
        for col in range(8):
            square = square_at(row, col, flipped)
            background = (211, 237, 235) if (row + col) % 2 == 0 else (85, 150, 115)
            if square in highlights:
                background = (70, 212, 240)
            y0, y1 = round(row * size / 8), round((row + 1) * size / 8)
            x0, x1 = round(col * size / 8), round((col + 1) * size / 8)
            tile = image[y0:y1, x0:x1]
            tile[:] = background
            piece = board.piece_at(square)
            if piece:
                name = ("w" if piece.color else "b") + piece.symbol().lower()
                rgba = cv2.imread(str(assets / f"{name}.png"), cv2.IMREAD_UNCHANGED)
                rgba = cv2.resize(rgba, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
                alpha = rgba[:, :, 3:4] / 255.0
                tile[:] = rgba[:, :, :3] * alpha + tile * (1 - alpha)
    return image


def find_board(image: np.ndarray, origin=(0, 0)) -> dict:
    """Find a large alternating board, tolerating a promotion menu or highlights."""
    scale = min(1.0, 1400 / max(image.shape[:2]))
    small = cv2.resize(image[:, :, :3], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    quantized = (small // 16).astype(np.int32)
    keys = quantized[:, :, 0] + 16 * quantized[:, :, 1] + 256 * quantized[:, :, 2]
    counts = np.bincount(keys.ravel(), minlength=4096)
    common = counts.argsort()[-10:][::-1]
    candidates = set()
    minimum = 240 * scale
    for i, a in enumerate(common):
        for b in common[i + 1:]:
            mask = ((keys == a) | (keys == b)).astype(np.uint8)
            total, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 4)
            for x, y, width, height, area in stats[1:]:
                if area < minimum ** 2 * .35:
                    continue
                for side in (width, height):
                    if side < minimum or side > max(image.shape[:2]) * scale:
                        continue
                    for left, top in ((x, y), (x + width - side, y), (x, y + height - side)):
                        if left >= 0 and top >= 0 and left + side <= small.shape[1] and top + side <= small.shape[0]:
                            candidates.add((int(left), int(top), int(side)))
    ranked = []
    for x, y, side in candidates:
        cells = []
        for row in range(8):
            for col in range(8):
                points = [small[min(small.shape[0]-1, int(y + (row + dy) * side / 8)),
                                min(small.shape[1]-1, int(x + (col + dx) * side / 8))]
                          for dy, dx in ((.12, .12), (.12, .88), (.88, .12), (.88, .88))]
                cells.append(np.median(points, axis=0))
        cells = np.asarray(cells, dtype=np.float32)
        parity = np.array([(row + col) % 2 for row in range(8) for col in range(8)])
        colors = [np.median(cells[parity == p], axis=0) for p in (0, 1)]
        if np.linalg.norm(colors[0] - colors[1]) < 55:
            continue
        errors = np.linalg.norm(cells - np.asarray(colors)[parity], axis=1)
        score = float(np.mean(errors < 38))
        if score >= .76:
            ranked.append((score, side, x, y))
    if not ranked:
        raise RecognitionError("No board found. Keep all 64 squares visible, or use Select manually.")
    score, side, x, y = max(ranked)
    return {"left": origin[0] + round(x / scale), "top": origin[1] + round(y / scale),
            "width": round(side / scale), "height": round(side / scale)}


def move_instruction(board, move, promotion_menu=False):
    piece = board.piece_at(move.from_square)
    if move.promotion:
        name = chess.piece_name(move.promotion)
        return f"Promote to {name}", (f"Choose the {name} in the promotion menu." if promotion_menu
                                    else f"Move your pawn to {chess.square_name(move.to_square)} and choose a {name}.")
    if board.is_castling(move):
        side = "kingside" if board.is_kingside_castling(move) else "queenside"
        return f"Castle {side}", f"Move your king from {chess.square_name(move.from_square)} to {chess.square_name(move.to_square)}."
    name = chess.piece_name(piece.piece_type)
    verb = "Capture" if board.is_capture(move) else "Move"
    return f"{name.capitalize()} to {chess.square_name(move.to_square)}", (
        f"{verb} with your {name}: {chess.square_name(move.from_square)} → {chess.square_name(move.to_square)}.")


def attacking_value(board, move):
    """A style preference, used only inside a narrow engine-score tolerance."""
    value = 0.0
    if board.is_capture(move):
        victim = board.piece_at(move.to_square)
        value += 1.5 + (victim.piece_type if victim else 1) * .08
    if board.gives_check(move):
        value += 2.0
    candidate = board.copy()
    candidate.push(move)
    enemy_king = candidate.king(candidate.turn)
    if enemy_king is not None:
        for square in chess.SQUARES:
            if chess.square_distance(square, enemy_king) <= 1:
                value += len(candidate.attackers(board.turn, square)) * .22
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type != chess.KING:
        advance = chess.square_rank(move.to_square) - chess.square_rank(move.from_square)
        value += (advance if board.turn else -advance) * .09
    return value


def choose_style(board, lines, style="Balanced"):
    valid = [line for line in lines if line.get("pv") and line["pv"][0] in board.legal_moves and line.get("score") is not None]
    if not valid:
        return lines[0] if lines else {}
    valid.sort(key=lambda line: line["score"].pov(board.turn), reverse=True)
    best = valid[0]
    selected = best
    score = best["score"].pov(board.turn)
    if style == "Aggressive" and not score.is_mate():
        eligible = [line for line in valid if not line["score"].pov(board.turn).is_mate()
                    and score.score() - line["score"].pov(board.turn).score() <= 35]
        selected = max(eligible, key=lambda line: (attacking_value(board, line["pv"][0]), line["score"].pov(board.turn)))
    elif style == "Fastest Checkmate":
        winning_mates = [line for line in valid
                         if line["score"].pov(board.turn).is_mate()
                         and line["score"].pov(board.turn).mate() > 0]
        if winning_mates:
            selected = max(winning_mates, key=lambda line: line["score"].pov(board.turn))
    result = dict(selected)
    result["style"] = style
    selected_score = selected["score"].pov(board.turn)
    result["style_loss_cp"] = (score.score() - selected_score.score()) if not score.is_mate() and not selected_score.is_mate() else 0
    return result
