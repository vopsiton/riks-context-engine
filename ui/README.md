# Web UI

Simple web-based chat interface for Rik's Context Engine.

## Usage

The UI expects a backend API server running at `http://localhost:8000`.

### Running the API server

```bash
cd src
pip install fastapi uvicorn
uvicorn riks_context_engine.api.server:app --reload
```

Then open `index.html` in a browser, or serve it:

```bash
python -m http.server 3000 --directory ui
```

### API Endpoints

- `GET /health` — Health check
- `GET /models` — List available models
- `POST /api/chat` — Send a chat message

```json
POST /api/chat
{
  "message": "Hello",
  "model": "gemma4-31b-it"
}
```

## Environment

Configure `API_URL` in `index.html` if your server is on a different port/host.
