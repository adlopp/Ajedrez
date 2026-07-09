import pygame
import sys
import chess
import chess.pgn
import wave
import struct
import math
from constants import *
from network import ChessNetwork


def make_sound(frequency=440, duration=0.1, volume=0.5, fade=0.02, harmonics=None):
    if harmonics is None:
        harmonics = [(1.0, 0), (0.5, 0), (0.25, 0)]
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    n_fade = int(sample_rate * fade)
    buf = []
    for i in range(n_samples):
        t = i / sample_rate
        envelope = 1.0
        if i < n_fade:
            envelope = i / n_fade
        elif i > n_samples - n_fade:
            envelope = (n_samples - i) / n_fade
        val = 0.0
        for amp, detune in harmonics:
            val += amp * math.sin(2 * math.pi * frequency * (1 + detune) * t)
        val = max(-1.0, min(1.0, val / 1.5))
        buf.append(struct.pack('<h', int(32767 * volume * envelope * val)))
    raw = b''.join(buf)
    return pygame.mixer.Sound(buffer=raw)


def square_to_display(sq, perspective):
    rank = sq // 8
    file = sq % 8
    if perspective == "black":
        return (rank, 7 - file)
    else:
        return (7 - rank, file)


def display_to_square(row, col, perspective):
    if perspective == "black":
        return row * 8 + (7 - col)
    else:
        return (7 - row) * 8 + col


def get_square_rect(row, col):
    return pygame.Rect(
        BOARD_X + col * SQUARE_SIZE,
        BOARD_Y + row * SQUARE_SIZE,
        SQUARE_SIZE,
        SQUARE_SIZE,
    )


def algebraic_to_display(alg, perspective):
    sq = chess.parse_square(alg)
    return square_to_display(sq, perspective)


class Button:
    def __init__(self, rect, text, color=COLOR_BUTTON, text_color=COLOR_TEXT):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color
        self.text_color = text_color

    def draw(self, screen, font):
        hover = self.rect.collidepoint(pygame.mouse.get_pos())
        c = tuple(min(x + 30, 255) for x in self.color) if hover else self.color
        pygame.draw.rect(screen, c, self.rect, border_radius=6)
        surf = font.render(self.text, True, self.text_color)
        screen.blit(surf, surf.get_rect(center=self.rect.center))

    def clicked(self, pos):
        return self.rect.collidepoint(pos)


class ChessClient:
    def __init__(self):
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("Ajedrez Online")
        self.clock = pygame.time.Clock()

        self.snd_move = make_sound(800, 0.06, 0.3, harmonics=[(1.0, 0), (0.4, 0.002), (0.2, -0.001)])
        self.snd_capture = make_sound(500, 0.12, 0.4, harmonics=[(1.0, 0), (0.6, 0.005), (0.3, -0.003)])
        self.snd_check = make_sound(1000, 0.15, 0.4, harmonics=[(1.0, 0), (0.7, 0.003), (0.4, -0.002)])
        self.snd_game_over = make_sound(400, 0.5, 0.4, harmonics=[(1.0, 0), (0.5, 0.001), (0.3, 0.002), (0.15, -0.001)])

        self.font_large = pygame.font.SysFont("segoeui", 46)
        self.font_med = pygame.font.SysFont("segoeui", 30)
        self.font_small = pygame.font.SysFont("segoeui", 22)
        self.font_tiny = pygame.font.SysFont("segoeui", 18)
        self.font_cap = pygame.font.SysFont("segoeuisymbol", 20)
        self.font_piece = pygame.font.SysFont("segoeuisymbol", 44)
        self.font_piece_small = pygame.font.SysFont("segoeuisymbol", 32)

        self.state = "menu"
        self.board = chess.Board()
        self.network = ChessNetwork(SERVER_URL)
        self.my_color = None
        self.perspective = "white"
        self.selected = None
        self.legal_targets = set()
        self.last_move = None
        self.input_code = ""
        self.room_code = ""
        self.status_text = ""
        self.error_text = ""
        self.move_log = []
        self.captured_white = []
        self.captured_black = []

        self.show_promo = False
        self.promo_from = None
        self.promo_to = None

        self.opponent_connected = False
        self.draw_offered = False
        self.draw_received = False
        self.rematch_offered_by = None
        self.game_over = False
        self.game_result_text = ""

        self.messages = []
        self.muted = False

    def play_sound(self, snd):
        if not self.muted:
            snd.play()

        self.buttons_menu = [
            Button((WINDOW_WIDTH//2-120, 260, 240, 50), "Crear Sala", COLOR_BUTTON_GREEN),
            Button((WINDOW_WIDTH//2-120, 330, 240, 50), "Unirse a Sala"),
        ]
        self.buttons_game = []
        self.running = True

    def run(self):
        while self.running:
            dt = self.clock.tick(60)
            self.handle_events()
            self.handle_network()
            self.draw()
            pygame.display.flip()
        pygame.quit()
        sys.exit()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self.handle_key(event)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.handle_click(event.pos)

    def handle_key(self, event):
        if self.state == "joining_room":
            if event.key == pygame.K_RETURN and self.input_code:
                self.do_join_room(self.input_code)
            elif event.key == pygame.K_BACKSPACE:
                self.input_code = self.input_code[:-1]
            elif event.key == pygame.K_ESCAPE:
                self.state = "menu"
                self.input_code = ""
            elif event.unicode and event.unicode.isprintable() and len(self.input_code) < 8:
                self.input_code += event.unicode.upper()
        elif self.state == "menu":
            if event.key == pygame.K_ESCAPE:
                self.running = False
        elif self.state in ("playing", "game_over"):
            if event.key == pygame.K_ESCAPE:
                self.network.disconnect()
                self.reset()
                self.state = "menu"

    def handle_click(self, pos):
        if self.state == "menu":
            for b in self.buttons_menu:
                if b.clicked(pos):
                    if b.text == "Crear Sala":
                        self.do_create_room()
                    else:
                        self.state = "joining_room"
                        self.input_code = ""
                        self.error_text = ""
                    break
            return

        if self.state == "joining_room":
            btn_rect = pygame.Rect(WINDOW_WIDTH//2-80, 290, 160, 44)
            if btn_rect.collidepoint(pos) and self.input_code:
                self.do_join_room(self.input_code)

        if self.state == "creating_room":
            if self.room_code:
                clipboard_rect = pygame.Rect(WINDOW_WIDTH//2-100, 310, 200, 36)
                if clipboard_rect.collidepoint(pos):
                    try:
                        pygame.scrap.put(pygame.SCRAP_TEXT, self.room_code.encode())
                    except:
                        pass

        if self.state == "playing":
            x, y = pos
            if hasattr(self, 'mute_rect') and self.mute_rect.collidepoint(pos):
                self.muted = not self.muted
            elif BOARD_X <= x < BOARD_X + BOARD_SIZE and BOARD_Y <= y < BOARD_Y + BOARD_SIZE:
                col = (x - BOARD_X) // SQUARE_SIZE
                row = (y - BOARD_Y) // SQUARE_SIZE
                self.handle_board_click(row, col)
            else:
                for b in self.buttons_game:
                    if b.clicked(pos):
                        self.handle_game_button(b.text)

        if self.state == "game_over":
            for b in self.buttons_game:
                if b.clicked(pos):
                    self.handle_game_button(b.text)

        if self.show_promo:
            promo_rects = self.get_promo_rects()
            for i, (rect, piece) in enumerate(promo_rects):
                if rect.collidepoint(pos):
                    self.do_promotion(piece)
                    break

    def handle_game_button(self, text):
        if text == "Rendirse":
            self.network.send({"type": "resign"})
        elif text == "Ofrecer Tablas":
            self.network.send({"type": "draw_offer"})
            self.draw_offered = True
            self.add_message("Has ofrecido tablas")
            self.update_game_buttons()
        elif text == "Aceptar Tablas" and self.draw_received:
            self.network.send({"type": "draw_response", "accept": True})
            self.draw_received = False
            self.update_game_buttons()
        elif text == "Rechazar Tablas" and self.draw_received:
            self.network.send({"type": "draw_response", "accept": False})
            self.draw_received = False
            self.add_message("Has rechazado las tablas")
            self.update_game_buttons()
        elif text == "Ofrecer Revancha":
            self.network.send({"type": "rematch"})
            self.add_message("Has ofrecido revancha")
        elif text == "Aceptar Revancha":
            self.network.send({"type": "rematch_response", "accept": True})
        elif text == "Rechazar Revancha":
            self.network.send({"type": "rematch_response", "accept": False})
            self.add_message("Has rechazado la revancha")
            self.state = "menu"
            self.reset()
        elif text == "Volver al Menú":
            self.network.disconnect()
            self.reset()
            self.state = "menu"

    def handle_board_click(self, row, col):
        if self.state != "playing":
            return

        my_turn = (self.board.turn == chess.WHITE and self.my_color == "white") or \
                  (self.board.turn == chess.BLACK and self.my_color == "black")
        if not my_turn:
            return

        sq = display_to_square(row, col, self.perspective)
        piece = self.board.piece_at(sq)
        my_color_bool = (self.my_color == "white")

        if self.selected is None:
            if piece and piece.color == my_color_bool:
                self.selected = (row, col)
                self.legal_targets = set()
                for m in self.board.legal_moves:
                    if m.from_square == sq:
                        tr, tc = square_to_display(m.to_square, self.perspective)
                        self.legal_targets.add((tr, tc))
        else:
            sr, sc = self.selected
            if (row, col) == (sr, sc):
                self.selected = None
                self.legal_targets = set()
                return

            from_sq = display_to_square(sr, sc, self.perspective)
            to_sq = sq

            if (row, col) in self.legal_targets:
                p = self.board.piece_at(from_sq)
                if p and p.piece_type == chess.PAWN:
                    to_rank = to_sq // 8
                    if to_rank in (0, 7):
                        self.promo_from = from_sq
                        self.promo_to = to_sq
                        self.show_promo = True
                        self.selected = None
                        self.legal_targets = set()
                        return

                self.execute_move(from_sq, to_sq, None)
            elif piece and piece.color == my_color_bool:
                self.selected = (row, col)
                self.legal_targets = set()
                for m in self.board.legal_moves:
                    if m.from_square == sq:
                        tr, tc = square_to_display(m.to_square, self.perspective)
                        self.legal_targets.add((tr, tc))
            else:
                self.selected = None
                self.legal_targets = set()

    def execute_move(self, from_sq, to_sq, promotion):
        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move in self.board.legal_moves:
            san = self.board.san(move)
            p = self.board.piece_at(to_sq)
            if p:
                sym = PIECE_UNICODE.get(p.symbol(), '?')
                (self.captured_black if p.color == chess.BLACK else self.captured_white).append(sym)
                self.play_sound(self.snd_capture)
            else:
                self.play_sound(self.snd_move)
            self.board.push(move)
            if self.board.is_check():
                self.play_sound(self.snd_check)
            self.last_move = (from_sq, to_sq)
            self.selected = None
            self.legal_targets = set()
            self.move_log.append(san)
            uci = chess.Move(from_sq, to_sq, promotion=promotion).uci()
            self.network.send({"type": "move", "uci": uci})

            outcome = self.board.outcome()
            if outcome:
                self.play_sound(self.snd_game_over)
                self.handle_game_end(outcome)
            else:
                self.draw_offered = False

    def do_promotion(self, piece_type):
        self.show_promo = False
        self.execute_move(self.promo_from, self.promo_to, piece_type)
        self.promo_from = None
        self.promo_to = None

    def get_promo_rects(self):
        pieces = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
        symbols = ['♛', '♜', '♝', '♞'] if self.my_color == "black" else ['♕', '♖', '♗', '♘']
        rects = []
        win_w = 220
        win_h = 60
        wx = (WINDOW_WIDTH - win_w) // 2
        wy = (WINDOW_HEIGHT - win_h) // 2
        for i, (pt, sym) in enumerate(zip(pieces, symbols)):
            r = pygame.Rect(wx + i * 55, wy, 50, 50)
            rects.append((r, pt, sym))
        return rects

    def handle_game_end(self, outcome):
        self.game_over = True
        winner = outcome.winner
        if outcome.termination == chess.Termination.CHECKMATE:
            w = "Blancas" if winner else "Negras"
            self.game_result_text = f"¡Jaque Mate! {w} ganan"
        elif outcome.termination == chess.Termination.STALEMATE:
            self.game_result_text = "Tablas por ahogado"
        elif outcome.termination == chess.Termination.INSUFFICIENT_MATERIAL:
            self.game_result_text = "Tablas (material insuficiente)"
        elif outcome.termination == chess.Termination.FIFTY_MOVES:
            self.game_result_text = "Tablas (regla de 50 movimientos)"
        elif outcome.termination == chess.Termination.THREEFOLD_REPETITION:
            self.game_result_text = "Tablas (triple repetición)"
        else:
            self.game_result_text = "Juego terminado"
        self.state = "game_over"
        self.update_game_buttons()

    def do_create_room(self):
        self.state = "creating_room"
        self.status_text = "Conectando..."
        self.network.start()

    def do_join_room(self, code):
        self.state = "waiting_to_join"
        self.status_text = f"Conectando a sala {code}..."
        self.network.start()

    def resign_game(self):
        self.network.send({"type": "resign"})

    def handle_network(self):
        msgs = self.network.poll()
        for msg in msgs:
            self.process_message(msg)

    def process_message(self, msg):
        t = msg.get("type")

        if t == "_connected":
            if self.state == "creating_room":
                self.network.send({"type": "create_room"})
            elif self.state == "waiting_to_join":
                self.network.send({"type": "join_room", "code": self.input_code.upper()})

        elif t == "_error":
            self.error_text = msg.get("message", "Error de conexión")
            self.add_message(f"Error: {self.error_text}")

        elif t == "_disconnected":
            if self.state != "menu":
                self.add_message("Desconectado del servidor")
                self.status_text = "Desconectado"

        elif t == "room_created":
            self.room_code = msg["code"]
            self.status_text = f"Código de sala: {self.room_code}"
            self.add_message(f"Sala {self.room_code} creada. Esperando oponente...")

        elif t == "error":
            self.error_text = msg.get("message", "Error")
            self.add_message(f"Error: {self.error_text}")
            if self.state in ("waiting_to_join",):
                self.state = "joining_room"

        elif t == "opponent_joined":
            self.my_color = msg["color"]
            self.perspective = self.my_color
            self.opponent_connected = True
            self.board.turn = chess.BLACK
            self.state = "playing"
            c = "Blancas" if self.my_color == "white" else "Negras"
            self.status_text = f"¡Oponente conectado! {c}: Tú"
            self.add_message(f"¡Oponente conectado! Juegas con {c}")
            self.update_game_buttons()

        elif t == "game_start":
            self.my_color = msg["color"]
            self.perspective = self.my_color
            self.opponent_connected = True
            self.board.turn = chess.BLACK
            self.state = "playing"
            c = "Blancas" if self.my_color == "white" else "Negras"
            self.status_text = f"¡Partida iniciada! {c}: Tú"
            self.add_message(f"Juegas con {c}")
            self.update_game_buttons()

        elif t == "move":
            try:
                uci = msg["uci"]
                move = chess.Move.from_uci(uci)
                if move not in self.board.legal_moves:
                    self.add_message(f"Movimiento inválido recibido: {uci}")
                    return
                san = self.board.san(move)
                p = self.board.piece_at(move.to_square)
                if p:
                    sym = PIECE_UNICODE.get(p.symbol(), '?')
                    (self.captured_black if p.color == chess.BLACK else self.captured_white).append(sym)
                    self.play_sound(self.snd_capture)
                else:
                    self.play_sound(self.snd_move)
                self.board.push(move)
                if self.board.is_check():
                    self.play_sound(self.snd_check)
                self.last_move = (move.from_square, move.to_square)
                self.move_log.append(san)
                outcome = self.board.outcome()
                if outcome:
                    self.play_sound(self.snd_game_over)
                    self.handle_game_end(outcome)
            except Exception as e:
                self.add_message(f"Error al procesar movimiento: {e}")

        elif t == "resign":
            self.game_over = True
            w = "Negras" if self.my_color == "white" else "Blancas"
            self.game_result_text = f"El oponente se rindió. ¡{w} ganan!"
            self.state = "game_over"
            self.update_game_buttons()
            self.add_message("El oponente se rindió")

        elif t == "draw_offer":
            self.draw_received = True
            self.add_message("El oponente ofrece tablas")
            self.update_game_buttons()

        elif t == "draw_response":
            if msg.get("accept"):
                self.game_over = True
                self.game_result_text = "Tablas acordadas"
                self.state = "game_over"
                self.update_game_buttons()
                self.add_message("Tablas acordadas")
            else:
                self.draw_offered = False
                self.draw_received = False
                self.add_message("El oponente rechazó las tablas")
                self.update_game_buttons()

        elif t == "opponent_disconnected":
            self.add_message("El oponente se desconectó")
            if self.state == "playing":
                self.game_over = True
                self.game_result_text = "Victoria por abandono del oponente"
                self.state = "game_over"
                self.update_game_buttons()

        elif t == "rematch":
            self.rematch_offered_by = "opponent"
            self.add_message("El oponente ofrece revancha")
            self.update_game_buttons()

        elif t == "rematch_response":
            if msg.get("accept"):
                self.add_message("¡Revancha aceptada!")
                self.reset_game()
                self.network.send({"type": "create_room"})
            else:
                self.rematch_offered_by = None
                self.add_message("El oponente rechazó la revancha")
                self.state = "menu"
                self.reset()

    def reset_game(self):
        self.board = chess.Board()
        self.board.turn = chess.BLACK
        self.selected = None
        self.legal_targets = set()
        self.last_move = None
        self.move_log = []
        self.captured_white = []
        self.captured_black = []
        self.show_promo = False
        self.game_over = False
        self.game_result_text = ""
        self.draw_offered = False
        self.draw_received = False
        self.rematch_offered_by = None
        self.messages = []
        self.network = ChessNetwork(SERVER_URL)

    def reset(self):
        self.board = chess.Board()
        self.my_color = None
        self.perspective = "white"
        self.selected = None
        self.legal_targets = set()
        self.last_move = None
        self.input_code = ""
        self.room_code = ""
        self.status_text = ""
        self.error_text = ""
        self.move_log = []
        self.captured_white = []
        self.captured_black = []
        self.show_promo = False
        self.opponent_connected = False
        self.draw_offered = False
        self.draw_received = False
        self.rematch_offered_by = None
        self.game_over = False
        self.game_result_text = ""
        self.messages = []

    def add_message(self, text):
        self.messages.append(text)
        if len(self.messages) > 20:
            self.messages.pop(0)

    def update_game_buttons(self):
        self.buttons_game = []
        cx = PANEL_X + PANEL_WIDTH // 2
        by = WINDOW_HEIGHT - 130
        bw = 140
        if self.state == "playing":
            self.buttons_game.append(
                Button((cx - bw//2, by, bw, 36), "Rendirse", COLOR_BUTTON_RED, COLOR_TEXT))
            if self.draw_received:
                self.buttons_game.append(
                    Button((cx - bw - 10, by + 46, bw, 36), "Aceptar Tablas", COLOR_BUTTON_GREEN, COLOR_TEXT))
                self.buttons_game.append(
                    Button((cx + 10, by + 46, bw, 36), "Rechazar Tablas", COLOR_BUTTON_RED, COLOR_TEXT))
            elif not self.draw_offered:
                self.buttons_game.append(
                    Button((cx - bw//2, by + 46, bw, 36), "Ofrecer Tablas", COLOR_BUTTON, COLOR_TEXT))
        elif self.state == "game_over":
            self.buttons_game.append(
                Button((cx - bw//2, by, bw, 36), "Ofrecer Revancha", COLOR_BUTTON_GREEN, COLOR_TEXT))
            if self.rematch_offered_by == "opponent":
                self.buttons_game.append(
                    Button((cx - bw - 10, by + 46, bw, 36), "Aceptar Revancha", COLOR_BUTTON_GREEN, COLOR_TEXT))
                self.buttons_game.append(
                    Button((cx + 10, by + 46, bw, 36), "Rechazar Revancha", COLOR_BUTTON_RED, COLOR_TEXT))
            self.buttons_game.append(
                Button((cx - bw//2, by + 92, bw, 36), "Volver al Menú", COLOR_BUTTON_GRAY, COLOR_TEXT))

    def draw(self):
        self.screen.fill(COLOR_BG)

        if self.state == "menu":
            self.draw_menu()
        elif self.state == "creating_room":
            self.draw_creating_room()
        elif self.state == "joining_room":
            self.draw_joining_room()
        elif self.state == "waiting_to_join":
            self.draw_waiting()
        elif self.state in ("playing", "game_over"):
            self.draw_game()
            if self.show_promo:
                self.draw_promo_dialog()

    def draw_menu(self):
        pygame.draw.rect(self.screen, COLOR_PANEL,
                         (WINDOW_WIDTH//2 - 200, 60, 400, 420), border_radius=14)

        title = self.font_large.render("♚ AJEDREZ ♔", True, (240, 240, 240))
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH//2, 110)))
        title2 = self.font_med.render("ONLINE", True, (180, 180, 190))
        self.screen.blit(title2, title2.get_rect(center=(WINDOW_WIDTH//2, 150)))
        sub = self.font_small.render("Juega contra un amigo en tiempo real", True, (150, 150, 160))
        self.screen.blit(sub, sub.get_rect(center=(WINDOW_WIDTH//2, 195)))

        pygame.draw.line(self.screen, (80, 80, 95),
                         (WINDOW_WIDTH//2 - 150, 220), (WINDOW_WIDTH//2 + 150, 220), 1)

        for b in self.buttons_menu:
            b.draw(self.screen, self.font_med)

        if self.error_text:
            err = self.font_small.render(self.error_text, True, (255, 100, 100))
            self.screen.blit(err, err.get_rect(center=(WINDOW_WIDTH//2, 430)))

    def draw_creating_room(self):
        pygame.draw.rect(self.screen, COLOR_PANEL,
                         (WINDOW_WIDTH//2 - 200, 60, 400, 400), border_radius=14)

        title = self.font_med.render("CREAR SALA", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH//2, 110)))

        if self.room_code:
            pygame.draw.rect(self.screen, (40, 45, 55),
                             (WINDOW_WIDTH//2 - 120, 180, 240, 60), border_radius=8)
            code_text = self.font_large.render(self.room_code, True, (100, 220, 100))
            self.screen.blit(code_text, code_text.get_rect(center=(WINDOW_WIDTH//2, 210)))
            inst = self.font_small.render("Comparte este código con tu amigo", True, (160, 160, 170))
            self.screen.blit(inst, inst.get_rect(center=(WINDOW_WIDTH//2, 270)))
            dots = ".".join(["."] * ((pygame.time.get_ticks() // 800) % 4))
            waiting = self.font_med.render(f"Esperando oponente{dots}", True, (180, 180, 180))
            self.screen.blit(waiting, waiting.get_rect(center=(WINDOW_WIDTH//2, 330)))
        else:
            dots = ".".join(["."] * ((pygame.time.get_ticks() // 600) % 4))
            loading = self.font_med.render(f"Conectando{dots}", True, COLOR_TEXT)
            self.screen.blit(loading, loading.get_rect(center=(WINDOW_WIDTH//2, 230)))
            if self.error_text:
                err = self.font_small.render(self.error_text, True, (255, 100, 100))
                self.screen.blit(err, err.get_rect(center=(WINDOW_WIDTH//2, 290)))

        back = self.font_small.render("ESC para volver", True, (130, 130, 140))
        self.screen.blit(back, back.get_rect(center=(WINDOW_WIDTH//2, 440)))

    def draw_joining_room(self):
        pygame.draw.rect(self.screen, COLOR_PANEL,
                         (WINDOW_WIDTH//2 - 200, 60, 400, 400), border_radius=14)

        title = self.font_med.render("UNIRSE A SALA", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH//2, 110)))

        prompt = self.font_small.render("Ingresa el código de la sala:", True, (180, 180, 180))
        self.screen.blit(prompt, prompt.get_rect(center=(WINDOW_WIDTH//2, 190)))

        input_rect = pygame.Rect(WINDOW_WIDTH//2-120, 220, 240, 44)
        pygame.draw.rect(self.screen, COLOR_INPUT_BG, input_rect, border_radius=8)
        border_color = (100, 180, 255) if self.input_code else (100, 100, 120)
        pygame.draw.rect(self.screen, border_color, input_rect, 2, border_radius=8)

        cursor = "|" if pygame.time.get_ticks() % 1000 < 500 else " "
        code_display = self.input_code + cursor
        surf = self.font_large.render(code_display, True, COLOR_TEXT)
        self.screen.blit(surf, surf.get_rect(center=input_rect.center))

        btn_rect = pygame.Rect(WINDOW_WIDTH//2-80, 290, 160, 44)
        btn_color = COLOR_BUTTON if self.input_code else COLOR_BUTTON_GRAY
        pygame.draw.rect(self.screen, btn_color, btn_rect, border_radius=8)
        btn_surf = self.font_med.render("Unirse", True, COLOR_TEXT)
        self.screen.blit(btn_surf, btn_surf.get_rect(center=btn_rect.center))

        if self.error_text:
            err = self.font_small.render(self.error_text, True, (255, 100, 100))
            self.screen.blit(err, err.get_rect(center=(WINDOW_WIDTH//2, 370)))

        back = self.font_small.render("ESC para volver", True, (130, 130, 140))
        self.screen.blit(back, back.get_rect(center=(WINDOW_WIDTH//2, 440)))

    def draw_waiting(self):
        dots = ".".join(["."] * ((pygame.time.get_ticks() // 600) % 4))
        title = self.font_med.render(f"Conectando{dots}", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_WIDTH//2, WINDOW_HEIGHT//2 - 20)))
        if self.error_text:
            err = self.font_small.render(self.error_text, True, (255, 100, 100))
            self.screen.blit(err, err.get_rect(center=(WINDOW_WIDTH//2, WINDOW_HEIGHT//2 + 40)))

    def draw_game(self):
        self.draw_board()
        self.draw_panel()
        if self.state == "game_over":
            self.draw_game_over_overlay()

    def draw_board(self):
        my_turn = (self.board.turn == chess.WHITE and self.my_color == "white") or \
                  (self.board.turn == chess.BLACK and self.my_color == "black")
        border_color = (150, 45, 45) if (my_turn and self.state == "playing") else (100, 90, 80)
        bx, by = BOARD_X - 6, BOARD_Y - 6
        bs = BOARD_SIZE + 12
        pygame.draw.rect(self.screen, border_color, (bx, by, bs, bs), border_radius=5)

        for row in range(8):
            for col in range(8):
                color = COLOR_LIGHT if (row + col) % 2 == 0 else COLOR_DARK
                rect = get_square_rect(row, col)
                pygame.draw.rect(self.screen, color, rect)

        if self.last_move:
            for sq in self.last_move:
                r, c = square_to_display(sq, self.perspective)
                s = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
                s.fill(COLOR_LAST_MOVE)
                self.screen.blit(s, get_square_rect(r, c))

        if self.selected:
            sr, sc = self.selected
            s = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
            s.fill(COLOR_SELECTED)
            self.screen.blit(s, get_square_rect(sr, sc))

        for tr, tc in self.legal_targets:
            rect = get_square_rect(tr, tc)
            has_piece = self.board.piece_at(display_to_square(tr, tc, self.perspective))
            if has_piece:
                pygame.draw.rect(self.screen, (180, 100, 80, 200), rect, 4)
            else:
                s = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
                s.fill(COLOR_HIGHLIGHT)
                self.screen.blit(s, rect)
                pygame.draw.circle(self.screen, (100, 140, 80), rect.center, SQUARE_SIZE//8)

        for row in range(8):
            for col in range(8):
                sq = display_to_square(row, col, self.perspective)
                piece = self.board.piece_at(sq)
                if piece:
                    sym = PIECE_UNICODE.get(piece.symbol(), '?')
                    color = (40, 40, 40) if piece.color else (245, 245, 245)
                    f = self.font_piece_small if piece.piece_type != chess.KING else self.font_piece
                    rect = get_square_rect(row, col)
                    outline_color = (100, 90, 80)
                    outline = f.render(sym, True, outline_color)
                    orect = outline.get_rect(center=rect.center)
                    for dx, dy in (-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2):
                        self.screen.blit(outline, orect.move(dx, dy))
                    surf = f.render(sym, True, color)
                    self.screen.blit(surf, surf.get_rect(center=rect.center))

        for i, label in enumerate(['a','b','c','d','e','f','g','h']):
            col = i if self.perspective == "white" else 7 - i
            s = self.font_tiny.render(label, True, (160, 155, 145))
            self.screen.blit(s, (BOARD_X + col*SQUARE_SIZE + SQUARE_SIZE-14, BOARD_Y + BOARD_SIZE + 4))

        for i in range(8):
            rank = 8 - i if self.perspective == "white" else i + 1
            s = self.font_tiny.render(str(rank), True, (160, 155, 145))
            self.screen.blit(s, (BOARD_X - 16, BOARD_Y + i*SQUARE_SIZE + 4))

        mute_text = "Silenciar" if not self.muted else "Sonido"
        mute_label = self.font_tiny.render(mute_text, True, (160, 155, 145))
        mx = BOARD_X + BOARD_SIZE - mute_label.get_width() - 4
        my = BOARD_Y + BOARD_SIZE + 4
        self.mute_rect = pygame.Rect(mx - 4, my - 2, mute_label.get_width() + 8, mute_label.get_height() + 4)
        pygame.draw.rect(self.screen, (70, 70, 80), self.mute_rect, border_radius=4)
        self.screen.blit(mute_label, (mx, my))

    def draw_panel(self):
        px, py = PANEL_X, 20
        pw, ph = PANEL_WIDTH, WINDOW_HEIGHT - 40
        pygame.draw.rect(self.screen, COLOR_PANEL, (px, py, pw, ph), border_radius=10)

        cx = px + pw // 2

        my_turn = (self.board.turn == chess.WHITE and self.my_color == "white") or \
                   (self.board.turn == chess.BLACK and self.my_color == "black")
        if self.state == "playing":
            turn_text = "Tu turno" if my_turn else "Turno del otro jugador"
        else:
            turn_text = "Turno: Blancas" if self.board.turn == chess.WHITE else "Turno: Negras"
        t_surf = self.font_med.render(turn_text, True, COLOR_TEXT)
        self.screen.blit(t_surf, t_surf.get_rect(midtop=(cx, 34)))

        if self.my_color:
            circle_color = (245, 245, 245) if self.my_color == "white" else (40, 40, 40)
            color_label = "Blancas" if self.my_color == "white" else "Negras"
            c_surf = self.font_small.render(color_label, True, (180, 180, 180))
            c_rect = c_surf.get_rect(midtop=(cx, 72))
            self.screen.blit(c_surf, c_rect)
            circle_y = c_rect.centery
            pygame.draw.circle(self.screen, circle_color, (cx - c_rect.width // 2 - 18, circle_y), 10)
            pygame.draw.circle(self.screen, (180, 180, 180), (cx - c_rect.width // 2 - 18, circle_y), 10, 1)

        pygame.draw.line(self.screen, (80, 80, 95), (px + 15, 98), (px + pw - 15, 98), 1)

        y = 112
        if self.captured_white or self.captured_black:
            cap_title = self.font_small.render("Capturas", True, (160, 160, 170))
            self.screen.blit(cap_title, cap_title.get_rect(midtop=(cx, y)))
            y += 24
            cap_pieces = []
            if self.captured_black:
                cap_pieces.extend(self.captured_black[:10])
            if self.captured_white:
                cap_pieces.extend(self.captured_white[:10])
            if cap_pieces:
                cap_x = cx - len(cap_pieces) * 9
                for sym in cap_pieces:
                    cs = self.font_cap.render(sym, True, COLOR_TEXT)
                    self.screen.blit(cs, cs.get_rect(midtop=(cap_x, y)))
                    cap_x += 18
                y += 22
            y += 6
            pygame.draw.line(self.screen, (80, 80, 95), (px + 15, y), (px + pw - 15, y), 1)
            y += 16

        log_title = self.font_small.render("Historial", True, (160, 160, 170))
        self.screen.blit(log_title, log_title.get_rect(midtop=(cx, y)))
        y += 26

        max_log = (WINDOW_HEIGHT - y - 170) // 17
        start = max(0, len(self.move_log) - max_log)
        for i in range(start, len(self.move_log)):
            num = (i // 2) + 1
            prefix = f"{num}." if i % 2 == 0 else ""
            txt = f"{prefix} {self.move_log[i]}"
            s = self.font_tiny.render(txt, True, (200, 200, 200))
            self.screen.blit(s, (px + 14, y))
            y += 17

        if self.state != "game_over":
            for b in self.buttons_game:
                b.draw(self.screen, self.font_small)

    def draw_game_over_overlay(self):
        s = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        s.fill((0, 0, 0, 180))
        self.screen.blit(s, (0, 0))

        box_w = 440
        box_h = 200 if not self.buttons_game else 260
        bx = (WINDOW_WIDTH - box_w) // 2
        by = (WINDOW_HEIGHT - box_h) // 2
        pygame.draw.rect(self.screen, (55, 55, 70), (bx, by, box_w, box_h), border_radius=14)
        pygame.draw.rect(self.screen, (130, 130, 150), (bx, by, box_w, box_h), 2, border_radius=14)

        result = self.font_large.render(self.game_result_text, True, COLOR_TEXT)
        self.screen.blit(result, result.get_rect(center=(WINDOW_WIDTH//2, by + 50)))

        sub = self.font_small.render("Presiona ESC para salir", True, (160, 160, 170))
        self.screen.blit(sub, sub.get_rect(center=(WINDOW_WIDTH//2, by + 90)))

        for i, btn in enumerate(self.buttons_game):
            btn.rect = pygame.Rect(bx + 20 + (i % 2) * 210, by + 125 + (i // 2) * 50, 200, 40)
            btn.draw(self.screen, self.font_small)

    def draw_promo_dialog(self):
        s = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        s.fill((0, 0, 0, 180))
        self.screen.blit(s, (0, 0))

        box_w, box_h = 280, 130
        bx, by = (WINDOW_WIDTH - box_w)//2, (WINDOW_HEIGHT - box_h)//2
        pygame.draw.rect(self.screen, (55, 55, 70), (bx, by, box_w, box_h), border_radius=12)
        pygame.draw.rect(self.screen, (130, 130, 150), (bx, by, box_w, box_h), 2, border_radius=12)

        pieces = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
        symbols = ['♛', '♜', '♝', '♞'] if self.my_color == "black" else ['♕', '♖', '♗', '♘']
        label = self.font_small.render("Elegir promoción:", True, COLOR_TEXT)
        self.screen.blit(label, label.get_rect(center=(WINDOW_WIDTH//2, by + 30)))

        for i, (pt, sym) in enumerate(zip(pieces, symbols)):
            x = bx + 20 + i * 60
            y = by + 55
            r = pygame.Rect(x, y, 50, 50)
            pygame.draw.rect(self.screen, (45, 45, 60), r, border_radius=6)
            pygame.draw.rect(self.screen, (130, 130, 150), r, 2, border_radius=6)
            color = (40, 40, 40) if self.my_color == "black" else (245, 245, 245)
            surf = self.font_large.render(sym, True, color)
            self.screen.blit(surf, surf.get_rect(center=r.center))


if __name__ == "__main__":
    game = ChessClient()
    game.run()
