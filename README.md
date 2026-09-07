# TSPO Room-Based Chat System

A high-performance, asynchronous room-based chat application built with **FastAPI**, **WebSockets**, **SQLite**, **Key-Value Storage**, and **VirusTotal Anti-Malware URL Filtering**.

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
   - Outputs timestamped events and security verdicts to both stdout and persistent `server.log`.

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

### **2. Environment Configuration (Optional)**
Create a `.env` file in the project root to configure optional VirusTotal URL reputation filtering:
```ini
VT_API_KEY=your_virustotal_api_key_here
```
*Note: The `.env` file is ignored by Git and must never be committed.*

### **3. Run the Server**
```bash
python -m Server.server
```
*The server starts on `http://0.0.0.0:8000` exposing both REST API endpoints and the WebSocket gateway (`/messanger`).*

### **4. Run the Client CLI**
Open a separate terminal window:
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

## 🔒 Security, DLP & Anti-Bot Protection

- **Authentication Guard:** Only registered users authenticated through `/login` or `/signup` can open a WebSocket chat session.
- **Data Loss Prevention (DLP) & Strike Engine:** Outgoing messages are inspected in real time for secrets (`secret_sauce`, `pineapple_protocol`), plaintext credentials (`password=`, `api_key=`), and credit-card PII. Violations drop the message, award a strike, and increment persistent risk score (`risk_score`).
- **Automated Ban Policy:** Reaching 3 strikes (`RISK_SCORE_BAN_THRESHOLD = 3`) permanently bans the account (`is_blocked = 1`), disconnects active WebSockets with code `1008`, and rejects future `/login` (HTTP `403`) and WebSocket connection attempts.
- **VirusTotal URL Reputation Filtering:** HTTP(S) URLs are extracted recursively from payloads and checked against VirusTotal. Malicious URLs are blocked immediately, sending a `security_warning` frame to the sender while logging the security verdict. Unchecked/failed lookups fail closed.
- **Input Sanitization:** Room names are strictly sanitized against alphanumeric regex rules (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`), payload size is capped (16 KB), frame size is capped (20 KB), and excessive JSON nesting depth is rejected.
- **Connection Recovery & Zombie Cleanup:** Sockets that experience network timeouts or drops are safely pruned from all active rooms without crashing the server.

---

## 🧪 Running Automated Tests

Run the full suite of unit, integration, security, and reputation tests:
```bash
python -m unittest discover tests -v
```
