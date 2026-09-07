# TSPO Room-Based Chat System

A high-performance, asynchronous room-based chat application built with **FastAPI**, **WebSockets**, **SQLite**, and **Key-Value Storage**.

---

## 🏗️ Architecture & Storage Overview

The application follows the **ByteByteGo Dual-Storage Architecture**:
1. **Relational Database (SQLite `users.db`):** 
   - Stores structured user accounts and security credentials.
   - Enforces unique usernames and cryptographic salted password hashing (**PBKDF2-HMAC-SHA256** with 100,000 iterations and 16-byte random salts).
   - Plaintext passwords are never stored.
2. **Key-Value Store (`messages_kv`):** 
   - Provides ultra-low latency, append-optimized storage for chat message history partitioned by room (`channel_id:message_id`).
3. **Centralized Logging (`logger.py`):**
   - Outputs timestamped events and security logs to both stdout and persistent `server.log`.

---

## 🎨 Design Patterns

### **1. Observer Pattern (Publish / Subscribe)**
- **Location:** `Server/room_manager.py` (`RoomManager`, `WebSocketObserver`)
- **Problem Solved:** Delivering real-time chat messages strictly to active members of a requested room without broadcasting to unrelated connections or polling.
- **Why Chosen:** Decouples the message routing engine from individual WebSocket transport implementations. Enables atomic subscription tracking and single-pass **Zombie Observer Cleanup** (automatically detaching dropped/unresponsive sockets from all rooms on disconnect).
- **Trade-off:** Requires maintaining bidirectional index tables (`_rooms` and `_observer_rooms`) and managing concurrency locking (`asyncio.Lock`).

### **2. Factory Pattern**
- **Location:** `Server/models.py` (`ModelFactory`, `Client`, `Room`)
- **Problem Solved:** Decouples domain model creation (`Client` and `Room` instances) from caller code across the server and client components.
- **Why Chosen:** Provides a single, stable construction seam where validation, session state, and default parameters can be modified without altering every direct object instantiation call site.
- **Trade-off:** Introduces an extra layer of indirection for lightweight data containers.

---

## 🚀 Quickstart & Setup

### **1. Installation**
```bash
# Clone the repository
git clone https://github.com/Scaleup-Excellenteam/checkpoint-igal-rabeaa-idan.git
cd checkpoint-igal-rabeaa-idan

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate   # On Linux/macOS
.venv\Scripts\activate      # On Windows

# Install dependencies
pip install -r requirements.txt
```

### **2. Run the Server**
```bash
python -m Server.server
```
*The server starts on `http://0.0.0.0:8000` with both the REST API and WebSocket gateway.*

### **3. Run the Client CLI**
Open a new terminal window:
```bash
python Client/client.py
```

---

## 💬 Client Commands Guide

| Command | Description |
| :--- | :--- |
| **`/join <room_id>`** | Join or switch to a room (e.g., `/join general`, `/join dev`) |
| **`/leave`** | Leave the current room |
| **`/list`** | View rooms you are currently in vs other active rooms on the server |
| **`/users`** | List all registered users and their status (`USER - STATUS`) |
| **`/help`** | Display the command help menu |
| **`/exit`** | Disconnect cleanly and quit the application |
| **`<any text>`** | Broadcast a chat message to everyone in your current room |

---

## 🔒 Security & Validation

- **Authentication Guard:** Only registered users authenticated through `/login` or `/signup` can open a WebSocket chat session.
- **Input Validation:** Room names are strictly sanitized against alphanumeric regex rules (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`), payload size is capped (16 KB), and dangerous JSON nesting depth is rejected.
- **Connection Recovery:** Sockets that experience network timeouts or drops are safely pruned from all active rooms without crashing the server. Reconnection creates a fresh observer.

---

## 🧪 Running Automated Tests

Run the full suite of unit and integration tests:
```bash
python -m unittest discover tests -v
```
