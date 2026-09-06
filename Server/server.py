from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI()
PORT = 8000

connected_clients = []

@app.get("/health")
async def health_check():
    return {"Status": "Healthy"}


@app.websocket("/messanger")
async def websocket_messanger(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    print(f"Client is now connected. Total clients in the system: {len(connected_clients)}")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Data received from the client to all clients: {data}")
            for client in connected_clients:
                await client.send_text(data)

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        print(f"Client has disconnected. Total clients in the system: {len(connected_clients)}")

def main():
    uvicorn.run(app, host="172.28.12.20", port=PORT)

if __name__ == "__main__":
    main()