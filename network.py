import asyncio
import json
import threading
import websockets
from queue import Queue


class ChessNetwork:
    def __init__(self, server_url):
        self.server_url = server_url
        self.websocket = None
        self.message_queue = Queue()
        self.connected = False
        self._thread = None
        self._loop = None

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect())

    async def _connect(self):
        try:
            self.websocket = await websockets.connect(self.server_url, ping_interval=20, ping_timeout=60)
            self.connected = True
            self.message_queue.put({"type": "_connected"})
            async for raw in self.websocket:
                data = json.loads(raw)
                self.message_queue.put(data)
        except (asyncio.CancelledError, websockets.exceptions.ConnectionClosed):
            pass
        except Exception as e:
            self.message_queue.put({"type": "_error", "message": str(e)})
        finally:
            self.connected = False
            self.message_queue.put({"type": "_disconnected"})

    def send(self, data):
        if self.websocket and self.connected and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self.websocket.send(json.dumps(data)), self._loop
            )
            future.add_done_callback(lambda f: f.result() if f.exception() else None)

    def poll(self):
        msgs = []
        while not self.message_queue.empty():
            msgs.append(self.message_queue.get())
        return msgs

    def disconnect(self):
        if self.websocket and self._loop:
            asyncio.run_coroutine_threadsafe(
                self.websocket.close(), self._loop
            )
