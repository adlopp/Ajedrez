import pygame

# CAMBIA ESTO por la URL de tu servidor en Fly.io
# Ejemplo: "wss://ajedrez-online-server.fly.dev"
SERVER_URL = "ws://localhost:8765"

WINDOW_WIDTH = 900
WINDOW_HEIGHT = 640

BOARD_SIZE = 480
SQUARE_SIZE = BOARD_SIZE // 8
BOARD_X = 40
BOARD_Y = 40

PANEL_X = BOARD_X + BOARD_SIZE + 30
PANEL_WIDTH = WINDOW_WIDTH - PANEL_X - 30

COLOR_LIGHT = (240, 217, 181)
COLOR_DARK = (181, 136, 99)
COLOR_SELECTED = (255, 255, 100, 128)
COLOR_HIGHLIGHT = (130, 151, 105, 160)
COLOR_LAST_MOVE = (205, 210, 106, 150)
COLOR_BG = (50, 50, 60)
COLOR_PANEL = (60, 60, 75)
COLOR_TEXT = (240, 240, 240)
COLOR_BUTTON = (70, 120, 200)
COLOR_BUTTON_HOVER = (90, 140, 220)
COLOR_BUTTON_RED = (200, 70, 70)
COLOR_BUTTON_GREEN = (70, 180, 70)
COLOR_BUTTON_GRAY = (100, 100, 100)
COLOR_INPUT_BG = (40, 40, 50)

PIECE_UNICODE = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}
