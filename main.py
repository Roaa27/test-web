"""
WebRTC Signaling Server for Unity Client
Receives video frames via WebRTC and displays them

Requirements:
pip install websockets aiortc opencv-python numpy aiohttp
"""

import asyncio
import json
import logging
import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaRecorder, MediaRelay
from av import VideoFrame
import websockets
from typing import Dict, Set

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store connected peers and their connections
peers: Dict[str, websockets.WebSocketServerProtocol] = {}
peer_connections: Dict[str, RTCPeerConnection] = {}
relay = MediaRelay()

# Frame buffer for display
current_frame = None
frame_lock = asyncio.Lock()


class VideoTransformTrack(VideoStreamTrack):
    """
    A video stream track that transforms frames from another track.
    """
    def __init__(self, track):
        super().__init__()
        self.track = track

    async def recv(self):
        global current_frame
        frame = await self.track.recv()
        
        # Convert frame to numpy array for OpenCV display
        img = frame.to_ndarray(format="bgr24")
        
        async with frame_lock:
            current_frame = img.copy()
        
        return frame


async def display_frames():
    """Display received video frames using OpenCV"""
    global current_frame
    
    cv2.namedWindow("WebRTC Stream", cv2.WINDOW_NORMAL)
    
    while True:
        async with frame_lock:
            if current_frame is not None:
                frame_to_show = current_frame.copy()
            else:
                frame_to_show = None
        
        if frame_to_show is not None:
            cv2.imshow("WebRTC Stream", frame_to_show)
        
        # Check for quit key (non-blocking)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        
        await asyncio.sleep(0.01)  # ~100 FPS check rate
    
    cv2.destroyAllWindows()


async def handle_websocket(websocket, path):
    """Handle WebSocket connections for signaling"""
    peer_id = None
    
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")
            
            logger.info(f"Received message type: {msg_type}")
            
            if msg_type == "register":
                # Register peer
                peer_id = data.get("peerId")
                peers[peer_id] = websocket
                logger.info(f"Peer registered: {peer_id}")
                
                # Send acknowledgment
                await websocket.send(json.dumps({
                    "type": "registered",
                    "peerId": peer_id
                }))
                
            elif msg_type == "offer":
                # Handle WebRTC offer
                target_peer_id = data.get("targetPeerId", "server")
                sender_peer_id = data.get("senderPeerId")
                sdp = data.get("sdp")
                
                logger.info(f"Received offer from {sender_peer_id}")
                
                # Create peer connection
                pc = RTCPeerConnection()
                peer_connections[sender_peer_id] = pc
                
                @pc.on("track")
                async def on_track(track):
                    logger.info(f"Received {track.kind} track from {sender_peer_id}")
                    
                    if track.kind == "video":
                        # Relay the video track for display
                        local_track = VideoTransformTrack(relay.subscribe(track))
                        logger.info("Video track is being processed")
                
                @pc.on("connectionstatechange")
                async def on_connectionstatechange():
                    logger.info(f"Connection state: {pc.connectionState}")
                
                @pc.on("datachannel")
                def on_datachannel(channel):
                    logger.info(f"Data channel created: {channel.label}")
                    
                    @channel.on("message")
                    def on_message(message):
                        logger.info(f"Data channel message: {message}")
                
                # Set remote description
                await pc.setRemoteDescription(RTCSessionDescription(
                    sdp=sdp,
                    type="offer"
                ))
                
                # Create answer
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                
                # Send answer back to Unity client
                await websocket.send(json.dumps({
                    "type": "answer",
                    "senderPeerId": "server",
                    "targetPeerId": sender_peer_id,
                    "sdp": pc.localDescription.sdp
                }))
                
                logger.info(f"Sent answer to {sender_peer_id}")
                
            elif msg_type == "ice-candidate":
                # Handle ICE candidate
                sender_peer_id = data.get("senderPeerId")
                candidate = data.get("candidate")
                
                if sender_peer_id in peer_connections:
                    # In aiortc, ICE candidates are handled automatically
                    logger.info(f"ICE candidate from {sender_peer_id}")
                
            elif msg_type == "test":
                # Handle test message
                logger.info(f"Test message: {data.get('message')}")
                await websocket.send(json.dumps({
                    "type": "test-response",
                    "message": "Test received by server"
                }))
    
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Connection closed for peer: {peer_id}")
    except Exception as e:
        logger.error(f"Error handling websocket: {e}", exc_info=True)
    finally:
        # Clean up
        if peer_id and peer_id in peers:
            del peers[peer_id]
        if peer_id and peer_id in peer_connections:
            await peer_connections[peer_id].close()
            del peer_connections[peer_id]


async def main():
    """Main server function"""
    # Start WebSocket server
    server = await websockets.serve(
        handle_websocket,
        "0.0.0.0",
        8765,
        ping_interval=20,
        ping_timeout=20
    )
    
    logger.info("WebSocket signaling server started on ws://0.0.0.0:8765")
    logger.info("Configure your Unity client to connect to: ws://YOUR_IP:8765")
    logger.info("Press Ctrl+C to stop the server")
    
    # Start frame display in background
    display_task = asyncio.create_task(display_frames())
    
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        # Clean up
        display_task.cancel()
        server.close()
        await server.wait_closed()
        
        # Close all peer connections
        for pc in peer_connections.values():
            await pc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped")