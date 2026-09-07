from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel
import uvicorn
import os

from Server.database import init_relational_db, init_kv_store
from Server.auth import create_user, verify_credentials
from Server.logger import logger

PORT = 8000
HOST = os.getenv("SERVER_HOST", "172.28.12.20")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize storage on startup
    logger.info("Initializing relational and key-value databases...")
    init_relational_db()
    init_kv_store()
    logger.info("Storage initialization completed.")
    yield
    logger.info("Server shutting down.")


app = FastAPI(title="ChatServer", lifespan=lifespan)


# ==============================================================================
# TEAMMATE 1: REST Endpoints (Health, Signup, Login)
# ==============================================================================

class UserCredentials(BaseModel):
    username: str
    password: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"Status": "Healthy"}


@app.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup_endpoint(credentials: UserCredentials):
    """
    Signup endpoint: creates a new user account with salted password hash.
    Rejects duplicate usernames with HTTP 400.
    """
    created = create_user(credentials.username, credentials.password)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{credentials.username}' is already taken or invalid."
        )
    return {"status": "success", "message": f"User '{credentials.username}' created successfully!"}


@app.post("/login", status_code=status.HTTP_200_OK)
async def login_endpoint(credentials: UserCredentials):
    """
    Login endpoint: verifies user credentials against relational DB.
    Returns HTTP 401 on failure.
    """
    is_valid = verify_credentials(credentials.username, credentials.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )
    return {"status": "success", "message": f"Welcome back, {credentials.username}!"}


# ==============================================================================
# TEAMMATE 3: Server Core & Observer Pattern (Room-based Routing)
# ==============================================================================

active_rooms = {}  # Maps room_id to Room objects / subscribers list
connected_clients = []  # Fallback global client list for basic messenger


def subscribe_to_room(room_id: str, websocket: WebSocket):
    """Observer: Add client to room's subscriber list."""
    if room_id not in active_rooms:
        active_rooms[room_id] = []
    active_rooms[room_id].append(websocket)
    logger.info(f"Subscribed client to room '{room_id}'")


def unsubscribe_from_room(room_id: str, websocket: WebSocket):
    """Observer: Remove client on disconnect."""
    if room_id in active_rooms and websocket in active_rooms[room_id]:
        active_rooms[room_id].remove(websocket)
        logger.info(f"Unsubscribed client from room '{room_id}'")


async def publish_to_room(room_id: str, message: str):
    """Observer: Iterate through room.subscribers and send message."""
    if room_id in active_rooms:
        for ws in active_rooms[room_id]:
            await ws.send_text(message)


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    """WebSocket endpoint for real-time messaging."""
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"Client connected. Total active clients: {len(connected_clients)}")
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Broadcasting message to {len(connected_clients)} clients: {data}")
            for client in connected_clients:
                await client.send_text(data)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"Client disconnected. Total active clients: {len(connected_clients)}")


def main():
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()