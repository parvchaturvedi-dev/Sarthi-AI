"""FastAPI backend for Nova's web UI.

Serves the single-page UI and bridges it to the conversation engine. All engine
work runs on ONE worker thread (so Playwright/SAPI/etc. stay thread-safe); HTTP
handlers enqueue a command and wait for the result. Memory reads are locked and
go direct so the sidebar stays responsive even mid-answer.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

from pydantic import BaseModel

# Module-level so annotations (which `from __future__ import annotations` turns
# into strings) resolve against module globals — FastAPI can't resolve
# UploadFile/File if they're only imported inside create_app().
from fastapi import File, Header, UploadFile

from ..settings import Settings

HERE = Path(__file__).parent


class ChatIn(BaseModel):
    text: str
    session_id: int | None = None
    speak: bool = True   # False => PC stays silent (mobile plays the audio itself)


class ModeIn(BaseModel):
    mode: str


class BrainIn(BaseModel):
    mode: str | None = None          # local | api
    provider: str | None = None      # ollama | openai | claude | gemini | grok
    model: str | None = None
    api_key: str | None = None


class PairIn(BaseModel):
    email: str
    device_name: str | None = None   # friendly name the phone gives this PC




def create_app(cfg, build_engine, build_speaker, settings: Settings):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse

    real = build_speaker()
    collector = {"buf": None}

    class CollectingSpeaker:
        def say(self, text: str) -> None:
            # Only speak aloud on the PC when the caller asked for it. Mobile
            # sends speak=False in mobile-only modes so the laptop stays silent.
            if collector.get("aloud", True):
                real.say(text)
            if collector["buf"] is not None and text:
                collector["buf"].append(text)

    engine = build_engine(CollectingSpeaker())
    engine.settings = settings          # engine can consult mode/connectors
    memory = engine.memory
    cmd_q: "queue.Queue" = queue.Queue()

    def worker() -> None:
        while True:
            cmd = cmd_q.get()
            if cmd is None:
                break
            kind = cmd[0]
            if kind == "chat":
                _, text, sid, name, speak, rq = cmd
                engine.user_name = name
                collector["aloud"] = speak
                if sid and sid != engine.session_id:
                    try:
                        engine.switch_session(sid)
                    except Exception:
                        pass
                collector["buf"] = []
                engine.pending_action = None
                try:
                    engine.address(text)
                except Exception as e:  # noqa: BLE001
                    collector["buf"].append(f"(error: {e})")
                replies, collector["buf"] = collector["buf"] or [], None
                pending, engine.pending_action = engine.pending_action, None
                rq.put((engine.session_id, replies, pending))
            elif kind == "new":
                cmd[1].put(engine.new_session())

    threading.Thread(target=worker, daemon=True).start()

    def _title(sid: int) -> str:
        for i, t, _ in memory.list_sessions(200):
            if i == sid:
                return t
        return "Chat"

    def _turns(sid: int):
        return [{"role": r, "content": c} for r, c in memory.session_turns(sid)]

    app = FastAPI()

    # allow the Next.js frontend (localhost:3000) to call this API
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # auth is via Authorization header, not cookies
        allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
    )
    from ..auth.routes import router as auth_router
    app.include_router(auth_router)

    @app.get("/")
    def index():
        return FileResponse(HERE / "index.html")

    @app.get("/app.js")
    def appjs():
        return FileResponse(HERE / "app.js", media_type="application/javascript")

    @app.get("/api/session/current")
    def current():
        sid = engine.session_id
        return {"id": sid, "title": _title(sid), "turns": _turns(sid)}

    @app.get("/api/sessions")
    def sessions():
        return {"sessions": [{"id": i, "title": t} for i, t, _ in memory.list_sessions()]}

    @app.get("/api/session/{sid}")
    def one(sid: int):
        return {"id": sid, "title": _title(sid), "turns": _turns(sid)}

    @app.post("/api/session/new")
    def new():
        rq: "queue.Queue" = queue.Queue()
        cmd_q.put(("new", rq))
        return {"id": rq.get()}

    @app.post("/api/chat")
    def chat(body: ChatIn, authorization: str = Header(default="")):
        name = None
        if authorization.startswith("Bearer "):
            try:
                import jwt as _jwt
                name = _jwt.decode(authorization[7:], os.getenv("JWT_SECRET", "dev-secret-change-me"),
                                   algorithms=["HS256"]).get("name")
            except Exception:
                pass
        rq: "queue.Queue" = queue.Queue()
        cmd_q.put(("chat", body.text, body.session_id, name, body.speak, rq))
        sid, replies, pending = rq.get()
        return {"replies": replies, "session_id": sid, "pending": pending}

    @app.post("/api/action/execute")
    def execute_action(body: dict):
        """Run a draft the user approved (email send / calendar add)."""
        from ..connectors.google import calendar_add, gmail_send
        try:
            kind = body.get("kind")
            acct = body.get("account")
            if kind == "email":
                gmail_send(acct, body["to"], body.get("subject", ""), body.get("body", ""))
                return {"ok": True, "message": f"Email sent to {body['to']}."}
            if kind == "calendar":
                calendar_add(acct, body["title"], body["start"], body.get("end"))
                return {"ok": True, "message": f"Added '{body['title']}' to your calendar."}
            return {"ok": False, "message": "Unknown action."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": str(e)}

    # --- Voice: transcribe an uploaded clip with faster-whisper (lazy-loaded) ---
    _stt = {"t": None}

    def _transcriber():
        if _stt["t"] is None:
            from ..voice.stt import Transcriber
            _stt["t"] = Transcriber(model="base.en", device="auto")
        return _stt["t"]

    @app.post("/api/transcribe")
    async def transcribe(file: UploadFile = File(...)):
        import os as _os
        import tempfile
        suffix = _os.path.splitext(file.filename or "")[1] or ".m4a"
        data = await file.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        try:
            t = _transcriber()
            text = t.transcribe_file(tmp.name) if t.available else None
            return {"text": (text or "").strip()}
        except Exception as e:  # noqa: BLE001
            return {"text": "", "error": str(e)}
        finally:
            try:
                _os.unlink(tmp.name)
            except Exception:
                pass

    # --- Control Your Device: natural command -> structured on-device action ---
    @app.post("/api/device/plan")
    def device_plan(body: dict):
        from ..core.device import plan_device_action
        text = (body or {}).get("text", "")
        try:
            llm = getattr(getattr(engine, "planner", None), "llm", None)
            reply, action = plan_device_action(llm, text)
            return {"reply": reply, "action": action}
        except Exception as e:  # noqa: BLE001
            return {"reply": f"(couldn't plan that: {e})", "action": None}

    @app.post("/api/device/operate")
    def device_operate(body: dict):
        """Decide the next in-app action for the phone's accessibility agent."""
        from ..core.device import plan_operate_step
        b = body or {}
        try:
            llm = getattr(getattr(engine, "planner", None), "llm", None)
            step = plan_operate_step(llm, b.get("goal", ""), b.get("screen", []), b.get("history", []))
            return step
        except Exception as e:  # noqa: BLE001
            return {"action": "ask", "say": str(e), "label": ""}

    @app.get("/api/tts")
    def tts(text: str):
        """Natural PC voice (edge-tts SwaraNeural) as mp3 — the phone plays this
        when online so the accent matches the desktop, not the device TTS."""
        from fastapi.responses import Response
        import asyncio
        t = (text or "").strip()[:900]
        if not t:
            return Response(status_code=204)
        try:
            if getattr(real, "_edge_ok", False):
                mp3 = asyncio.run(real._edge_synth(t))
                if mp3:
                    return Response(content=bytes(mp3), media_type="audio/mpeg")
        except Exception:
            pass
        return Response(status_code=503)

    @app.post("/api/stop")
    def stop_speaking():
        """Stop the current response's audio on the PC (best-effort)."""
        collector["aloud"] = False          # silence any remaining says this turn
        try:
            real.stop()
        except Exception:
            pass
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return settings.public()

    @app.post("/api/settings")
    def set_settings(body: ModeIn):
        settings.set_mode(body.mode)
        return {"ok": True, "mode": settings.mode}

    @app.get("/api/whoami")
    def whoami():
        """Lets a phone on the same Wi-Fi discover + identify this PC (no auth).
        `owner` is the account this PC is paired to, so the phone can find ITS PC."""
        return {"app": "sarthi", "name": settings.device_name,
                "owner": settings.owner_email, "mode": settings.mode}

    @app.post("/api/pair")
    def pair(body: PairIn):
        """Phone claims this PC for its account — the 'Connect' handshake."""
        settings.set_owner(body.email, body.device_name)
        return {"ok": True, "owner": settings.owner_email, "name": settings.device_name}

    @app.get("/api/brain/models")
    def brain_models():
        """Locally-installed Ollama models, for the 'run locally' dropdown."""
        import requests
        try:
            r = requests.get(f"{cfg.get('brain.ollama_url')}/api/tags", timeout=3)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
        except Exception:
            names = []
        return {"local_models": names,
                "providers": ["openai", "claude", "gemini", "grok"]}

    @app.post("/api/brain")
    def set_brain(body: BrainIn):
        settings.set_brain(mode=body.mode, provider=body.provider,
                           model=body.model, api_key=body.api_key)
        from ..main import rebuild_brain
        rebuild_brain(engine, cfg, settings)
        # quick validation so the UI can show Connected / an error
        working, error = True, None
        b = settings.brain()
        llm = getattr(engine.planner, "llm", None)
        if llm is None:
            working, error = False, "No brain available (check Ollama or API key)."
        elif b.get("mode") == "api":
            try:
                out = llm.chat_text([{"role": "user", "content": "reply with the word ok"}])
                if not out:
                    working, error = False, "API did not respond — check the key/model."
            except Exception as e:  # noqa: BLE001
                working, error = False, str(e)[:200]
        pub = settings.public().get("brain", {})
        return {"ok": True, "brain": pub, "working": working, "error": error}

    @app.post("/api/connectors/google/connect")
    def connect_google():
        from ..connectors.google import connect, has_credentials
        if not has_credentials():
            return {"ok": False, "error": "setup_needed"}
        try:
            email = connect()               # one login → Gmail + Calendar + Drive + Contacts
            settings.set_google_connected(email)
            return {"ok": True, "email": email}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    @app.post("/api/connectors/google/disconnect")
    def disconnect_google():
        settings.set_google_connected("")
        return {"ok": True}

    return app


def run_app(cfg, build_engine, build_speaker, port: int = 8760) -> None:
    import uvicorn

    try:
        from dotenv import load_dotenv
        load_dotenv()                       # backend/.env -> Oracle / JWT / Google
    except Exception:
        pass
    settings = Settings()
    app = create_app(cfg, build_engine, build_speaker, settings)

    try:                                     # Windows console is cp1252 by default
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"Sarthi backend API:  http://127.0.0.1:{port}  (LAN: http://0.0.0.0:{port})")
    print("Frontend (Next.js):  run `npm run dev` in frontend/ -> http://localhost:3000")
    print("Mobile (Expo):       phone on same Wi-Fi -> set Server URL to your PC's LAN IP")
    # 0.0.0.0 so the phone (Expo) can reach it over Wi-Fi, not just localhost.
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
