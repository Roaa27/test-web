import asyncio
import json
import logging
import os
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc-server")

peers: Dict[str, websockets.WebSocketServerProtocol] = {}
peer_connections: Dict[str, RTCPeerConnection] = {}


async def handle_websocket(websocket):
    peer_id = None

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            logger.info(f"Message type: {msg_type}")

            # Register peer
            if msg_type == "register":
                peer_id = data.get("peerId")
                peers[peer_id] = websocket

                await websocket.send(json.dumps({
                    "type": "registered",
                    "peerId": peer_id
                }))

            # WebRTC offer
            elif msg_type == "offer":
                sender_peer_id = data.get("senderPeerId")
                sdp = data.get("sdp")

                pc = RTCPeerConnection()
                peer_connections[sender_peer_id] = pc

                @pc.on("connectionstatechange")
                async def on_connectionstatechange():
                    logger.info(f"{sender_peer_id} state: {pc.connectionState}")

                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=sdp, type="offer")
                )

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                await websocket.send(json.dumps({
                    "type": "answer",
                    "senderPeerId": "server",
                    "targetPeerId": sender_peer_id,
                    "sdp": pc.localDescription.sdp
                }))

            elif msg_type == "test":
                await websocket.send(json.dumps({
                    "type": "test-response",
                    "message": "Server is alive"
                }))

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Disconnected: {peer_id}")

    finally:
        if peer_id in peers:
            del peers[peer_id]

        if peer_id in peer_connections:
            await peer_connections[peer_id].close()
            del peer_connections[peer_id]


async def main():
    port = int(os.environ.get("PORT", 8000))

    async with websockets.serve(
        handle_websocket,
        "0.0.0.0",
        port
    ):
        logger.info(f"WebSocket running on port {port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
