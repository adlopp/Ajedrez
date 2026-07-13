import asyncio
import json
import os
import websockets
import string
import random
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chess-server")

rooms = {}
pending_deletions = {}
ROOM_DELETE_TIMEOUT = 60


def generate_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in rooms:
            return code


async def delayed_delete(code):
    await asyncio.sleep(ROOM_DELETE_TIMEOUT)
    if code in rooms:
        room = rooms[code]
        for p in room["players"]:
            if p.open:
                try:
                    await p.send(json.dumps({"type": "room_expired", "message": "La sala ha expirado por inactividad"}))
                except Exception:
                    pass
        del rooms[code]
        log.info("[%s] Sala eliminada por timeout", code)
    pending_deletions.pop(code, None)


async def handler(ws):
    my_room = None
    try:
        log.info("Conexion nueva desde %s", ws.remote_address)
        async for raw in ws:
            data = json.loads(raw)
            t = data.get("type")

            if t == "create_room":
                code = generate_code()
                rooms[code] = {"players": [ws], "host": ws}
                my_room = code
                if code in pending_deletions:
                    pending_deletions[code].cancel()
                    pending_deletions.pop(code, None)
                await ws.send(json.dumps({"type": "room_created", "code": code}))
                log.info("[%s] Sala creada. Total: %d", code, len(rooms))

            elif t == "join_room":
                code = data.get("code", "").upper()
                room = rooms.get(code)
                if room is None:
                    await ws.send(json.dumps({"type": "error", "message": "Sala no encontrada"}))
                    log.warning("Sala %s no encontrada. Existentes: %s", code, list(rooms.keys()))
                elif len(room["players"]) >= 2:
                    await ws.send(json.dumps({"type": "error", "message": "Sala llena"}))
                    log.warning("[%s] Sala llena", code)
                else:
                    if code in pending_deletions:
                        pending_deletions[code].cancel()
                        pending_deletions.pop(code, None)
                        log.info("[%s] Delete cancelado - jugador se une", code)
                    room["players"].append(ws)
                    my_room = code
                    await room["players"][0].send(json.dumps({"type": "opponent_joined", "color": "black"}))
                    await room["players"][1].send(json.dumps({"type": "game_start", "color": "white"}))
                    log.info("[%s] Jugador se unio. Host=black, Joiner=white", code)

            elif t in ("move", "resign", "draw_offer", "draw_response", "rematch", "rematch_response", "chat"):
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

    except websockets.exceptions.ConnectionClosed:
        log.info("Conexion cerrada (room=%s)", my_room)
    except Exception as e:
        log.error("Error en handler: %s", e)
    finally:
        if my_room and my_room in rooms:
            room = rooms[my_room]
            if ws in room["players"]:
                room["players"].remove(ws)

            for p in room["players"]:
                if p.open:
                    try:
                        await p.send(json.dumps({"type": "opponent_disconnected", "timeout": ROOM_DELETE_TIMEOUT}))
                    except Exception:
                        pass

            if my_room not in pending_deletions:
                task = asyncio.create_task(delayed_delete(my_room))
                pending_deletions[my_room] = task
            log.info("[%s] Jugador desconectado. Players restantes: %d. Delete en %ds", my_room, len(room["players"]), ROOM_DELETE_TIMEOUT)


async def main():
    port = int(os.environ.get("PORT", 8765))
    log.info("Servidor de ajedrez iniciado en puerto %d", port)
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
