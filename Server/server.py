from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from pydantic import BaseModel
import uvicorn
import os

from Server.database import init_relational_db, init_kv_store
from Server.auth import register_user, authenticate_user
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
connected_clients = []


# ==========================================
# PYDANTIC SCHEMAS
# ==========================================

class UserCredentials(BaseModel):
    username: str
    password: str


# ==========================================
# REST ENDPOINTS (Health & Authentication)
# ==========================================

@app.get("/health")
async def health_check():
    return {"Status": "Healthy"}


@app.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(credentials: UserCredentials):
    success, message = register_user(credentials.username, credentials.password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )
    return {"status": "success", "message": message}


@app.post("/login", status_code=status.HTTP_200_OK)
async def login(credentials: UserCredentials):
    success, message = authenticate_user(credentials.username, credentials.password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message
        )
    return {"status": "success", "message": message}


# ==========================================
# WEBSOCKET MESSENGER
# ==========================================

@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"Client connected. Total active clients: {len(connected_clients)}")
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Broadcasting message from client to {len(connected_clients)} clients: {data}")
            for client in connected_clients:
                await client.send_text(data)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"Client disconnected. Total active clients: {len(connected_clients)}")


def main():
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()