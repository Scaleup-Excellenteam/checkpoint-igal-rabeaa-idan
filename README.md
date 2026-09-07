# Room-based WebSocket chat

The server implements a concurrency-safe Observer pattern: `RoomManager` is the
subject/publisher and each connected WebSocket is an observer. Membership is
tracked both by room and by connection, allowing a failed connection to be
removed from every room in one cleanup operation.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m Server.server
```

The WebSocket endpoint is `ws://127.0.0.1:8000/messanger`. To run the included
terminal client:

```bash
.venv/bin/python Client/client.py
```

## Protocol

Every client frame is a JSON object containing `room` and `payload`. `action` is
optional and defaults to `publish`.

```json
{"action":"subscribe","room":"general","payload":null}
{"action":"publish","room":"general","payload":{"text":"hello"}}
{"action":"unsubscribe","room":"general","payload":null}
```

A connection must subscribe before it can publish. Published envelopes are sent
only to the requested room's subscribers. Room names are trimmed, allow only
letters, numbers, `.`, `_`, and `-`, and are limited to 64 characters. Frames,
payload size, nesting depth, unknown fields, null characters, and non-finite
numbers are validated before routing.

Failed sends and sends exceeding five seconds remove the stale observer from all
rooms. Protocol ping/pong also detects silent peers. Handler-level cleanup runs in
`finally`, so both orderly and unexpected disconnects are safe. A reconnect is
simply a new observer and may subscribe normally.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```
