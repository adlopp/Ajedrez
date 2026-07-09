import asyncio
import json
import os
import websockets
import string
import random

rooms = {}

def generate_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def handler(ws):
    my_room = None
    try:
        async for raw in ws:
            data = json.loads(raw)
            t = data.get("type")

            if t == "create_room":
                code = generate_code()
                rooms[code] = {"players": [ws], "host": ws}
                my_room = code
                await ws.send(json.dumps({"type": "room_created", "code": code}))

            elif t == "join_room":
                code = data.get("code", "").upper()
                room = rooms.get(code)
                if room is None:
                    await ws.send(json.dumps({"type": "error", "message": "Sala no encontrada"}))
                elif len(room["players"]) >= 2:
                    await ws.send(json.dumps({"type": "error", "message": "Sala llena"}))
                else:
                    room["players"].append(ws)
                    my_room = code
                    colors = ["white", "black"]
                    random.shuffle(colors)
                    await room["players"][0].send(json.dumps({"type": "opponent_joined", "color": colors[0]}))
                    await room["players"][1].send(json.dumps({"type": "game_start", "color": colors[1]}))

            elif t == "move":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

            elif t == "resign":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

            elif t == "draw_offer":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

            elif t == "draw_response":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

            elif t == "rematch":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

            elif t == "rematch_response":
                if my_room and my_room in rooms:
                    room = rooms[my_room]
                    for p in room["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))
                    if data.get("accept"):
                        room["players"] = [room["players"][0], room["players"][1]]

            elif t == "chat":
                if my_room and my_room in rooms:
                    for p in rooms[my_room]["players"]:
                        if p != ws:
                            await p.send(json.dumps(data))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if my_room and my_room in rooms:
            room = rooms[my_room]
            for p in room["players"]:
                if p != ws and p.open:
                    try:
                        await p.send(json.dumps({"type": "opponent_disconnected"}))
                    except:
                        pass
            del rooms[my_room]


async def main():
    port = int(os.environ.get("PORT", 8765))
    print(f"Servidor de ajedrez iniciado en puerto {port}")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
