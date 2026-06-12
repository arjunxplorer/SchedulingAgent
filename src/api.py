"""FastAPI web server — serves the React frontend and provides the scheduling API."""

import os
import json
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.graph_runner import (
    build_graph,
    create_default_model,
    default_session_state,
    stream_graph_events,
    run_graph_async,
)
from src.tools import (
    get_calendar_events,
    get_tasks,
    get_calendar_service,
    get_tasks_service,
    search_events,
    get_current_time,
)
from src.voice_ws import voice_router

load_dotenv()

CREDENTIALS_FILE = "credentials.json"

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="SchedulingAgent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Voice WebSocket ─────────────────────────────────────────────────────────
app.include_router(voice_router)

# ── Graph & Session State ────────────────────────────────────────────────────

_graph = None

def get_graph():
    global _graph
    if _graph is None:
        model = create_default_model()
        _graph = build_graph(model)
    return _graph

# Per-session state (single-user tool, so one default session is fine)
sessions: dict[str, dict] = {"default": default_session_state()}


def get_session(session_id: str = "default") -> dict:
    if session_id not in sessions:
        sessions[session_id] = default_session_state()
    return sessions[session_id]


def is_google_authenticated() -> bool:
    """Check if Google credentials are available without triggering OAuth."""
    return os.path.exists("token.json") or os.path.exists(CREDENTIALS_FILE)


# ── Request/Response Models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ConfirmRequest(BaseModel):
    confirmed: bool
    session_id: str = "default"


# ── Chat Endpoint (SSE) ─────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream graph execution as Server-Sent Events."""
    print(f"[CHAT] message={req.message!r}, session_id={req.session_id!r}")
    session = get_session(req.session_id)

    try:
        graph = get_graph()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to initialize model: {e}"},
        )

    async def event_stream():
        try:
            async for event in stream_graph_events(graph, req.message, session):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Events Endpoint ─────────────────────────────────────────────────────────

@app.get("/events")
async def list_events(
    date_range: str = Query("today", description="today, tomorrow, this_week, next_week, or YYYY-MM-DD"),
    query: str = Query("", description="Optional text filter"),
):
    """List calendar events for a date range."""
    if not is_google_authenticated():
        return JSONResponse(
            status_code=401,
            content={"error": "Google Calendar not connected. Please authenticate first."},
        )
    try:
        events = search_events.invoke({"query": query, "date_range": date_range})
        return {"events": events}
    except FileNotFoundError:
        return JSONResponse(
            status_code=401,
            content={"error": "Google Calendar credentials not found. Please add credentials.json and authenticate."},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Tasks Endpoint ──────────────────────────────────────────────────────────

@app.get("/tasks")
async def list_user_tasks():
    """List all incomplete tasks."""
    if not is_google_authenticated():
        return JSONResponse(
            status_code=401,
            content={"error": "Google Tasks not connected. Please authenticate first."},
        )
    try:
        tasks = get_tasks()
        task_list = []
        for t in tasks:
            task_list.append({
                "id": t.id,
                "title": t.title,
                "notes": t.notes,
                "due_date": t.due_date,
            })
        return {"tasks": task_list}
    except FileNotFoundError:
        return JSONResponse(
            status_code=401,
            content={"error": "Google Calendar credentials not found. Please add credentials.json and authenticate."},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Auth Endpoints ───────────────────────────────────────────────────────────

@app.get("/auth/status")
async def auth_status():
    """Check if Google Calendar is authenticated."""
    if not os.path.exists("token.json") and not os.path.exists(CREDENTIALS_FILE):
        return {"authenticated": False, "reason": "no_credentials"}
    try:
        service = get_calendar_service()
        calendar_list = service.calendarList().list(maxResults=1).execute()
        return {"authenticated": True}
    except FileNotFoundError:
        return {"authenticated": False, "reason": "no_credentials"}
    except Exception:
        return {"authenticated": False, "reason": "token_expired"}


@app.post("/auth/login")
async def auth_login():
    """Start the OAuth flow. Returns the authorization URL.

    Uses GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET from .env if available,
    otherwise falls back to credentials.json file.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
    ]

    REDIRECT_URI = "http://localhost:8000/auth/callback"

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    try:
        if client_id and client_secret:
            client_config = {
                "web": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [REDIRECT_URI],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES, redirect_uri=REDIRECT_URI)
        elif os.path.exists(CREDENTIALS_FILE):
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES, redirect_uri=REDIRECT_URI)
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "No Google credentials configured.",
                    "help": "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
                },
            )

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        app.state.oauth_flow = flow
        return {"auth_url": auth_url}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle the OAuth callback from Google."""
    from fastapi.responses import HTMLResponse

    code = request.query_params.get("code")
    if not code:
        return JSONResponse(status_code=400, content={"error": "Missing authorization code"})

    flow = getattr(app.state, "oauth_flow", None)
    if not flow:
        return JSONResponse(status_code=400, content={"error": "No OAuth flow in progress"})

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save the token
        with open("token.json", "w") as f:
            f.write(creds.to_json())

        # Reset service singletons so they pick up the new token
        import src.tools.calendar_tools as ct
        ct._calendar_service = None
        ct._tasks_service = None

        # Return HTML that closes the popup and notifies the parent window
        return HTMLResponse("""
            <html><body>
            <p>Authentication successful! You can close this window.</p>
            <script>
                if (window.opener) {
                    window.opener.postMessage("google-auth-success", "*");
                }
                window.close();
            </script>
            </body></html>
        """)
    except Exception as e:
        error_msg = str(e).replace("&", "&amp;").replace("<", "&lt;")
        return HTMLResponse(
            '<html><body>'
            '<p>Authentication failed: ' + error_msg + '</p>'
            '<script>'
            'if (window.opener) {'
            '  window.opener.postMessage("google-auth-failed", "*");'
            '}'
            '</script>'
            '</body></html>'
        )


@app.post("/auth/logout")
async def auth_logout():
    """Remove stored credentials and reset services."""
    try:
        if os.path.exists("token.json"):
            os.remove("token.json")

        import src.tools.calendar_tools as ct
        ct._calendar_service = None
        ct._tasks_service = None

        return {"success": True, "message": "Logged out"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Static File Serving (React build) ───────────────────────────────────────

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for all non-API routes."""
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
