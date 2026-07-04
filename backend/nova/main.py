"""Nova entry point.

    python -m nova.main                      # floating UI (voice if mic is set up)
    python -m nova.main --text "open notepad"  # one-shot, no UI — great for testing
    python -m nova.main --dry-run --text "open chrome"  # plan+speak, never touch OS
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import threading

from .agent.executor import Executor
from .brain.chat import Chat
from .brain.llm import OllamaClient
from .brain.planner import Planner
from .config import load_config
from .core.conversation import ConversationEngine, State
from .memory.store import Memory
from .pipeline import Pipeline
from .schema import Step
from .voice.stt import Transcriber
from .voice.tts import Speaker


def _local_ollama(cfg, model=None):
    """A reachable local Ollama client, or None. Used as the local brain AND
    (always) for embeddings + vision, so those stay on-device."""
    try:
        c = OllamaClient(
            cfg.get("brain.ollama_url"),
            model or cfg.get("brain.model"),
            int(cfg.get("brain.timeout_s", 90)),
            embed_model=cfg.get("brain.embed_model", "nomic-embed-text"),
        )
        return c if c.available() else None
    except Exception:
        return None


def _build_chat_client(cfg, settings):
    """Pick the brain the user chose in Settings: fully local, or a cloud API."""
    log = logging.getLogger("nova")
    brain = settings.brain() if settings else {}
    mode = brain.get("mode") or "local"

    if mode == "api" and brain.get("api_key"):
        from .brain.providers import build_chat_client
        c = build_chat_client(brain.get("provider", ""), brain.get("model", ""),
                              brain.get("api_key", ""), int(cfg.get("brain.timeout_s", 90)))
        if c and c.available():
            log.info("brain: API %s (%s)", brain.get("provider"), getattr(c, "model", ""))
            return c
        log.warning("brain: API mode but provider/key invalid — falling back to local")

    # local Ollama (use the chosen local model, e.g. qwen or gpt-oss, else config)
    local_model = brain.get("model") if (mode == "local" and brain.get("provider", "ollama") == "ollama") else None
    c = _local_ollama(cfg, local_model)
    if c is not None:
        log.info("brain: Ollama (%s)", c.model)
        threading.Thread(target=c.warm, daemon=True).start()
        return c
    log.warning("brain: no LLM reachable — rule planner + offline chat")
    return None


def _build_brain(cfg, settings=None):
    """Build planner + chat on the user-chosen brain (local model or cloud API)."""
    if settings is None:
        try:
            from .settings import Settings
            settings = Settings()
        except Exception:
            settings = None
    llm = _build_chat_client(cfg, settings)
    language = cfg.get("assistant.language", "hindi")
    planner = Planner(
        llm,
        fallback_to_rules=bool(cfg.get("brain.fallback_to_rules", True)),
        language=language,
    )
    chat = Chat(llm, language=language)
    return planner, chat


def rebuild_brain(engine, cfg, settings) -> None:
    """Hot-swap the brain when the user changes it in Settings (no restart)."""
    planner, chat = _build_brain(cfg, settings)
    engine.planner = planner
    engine.pipeline.planner = planner
    engine.chat = chat
    if getattr(engine, "researcher", None) is not None:
        engine.researcher.llm = getattr(planner, "llm", None)


def _build_engine(cfg, planner, chat, speaker, transcriber=None, dry_run=False) -> ConversationEngine:
    executor = Executor(
        speaker.say,
        dry_run=dry_run or bool(cfg.get("agent.dry_run", False)),
        step_pause_s=float(cfg.get("agent.step_pause_s", 0.6)),
        confirm_sensitive=bool(cfg.get("agent.confirm_sensitive", True)),
        confirm_fn=_make_confirm_fn(speaker, transcriber) if transcriber else None,
        use_managed_browser=bool(cfg.get("browser.managed", True)),
        browser_profile=cfg.get("browser.profile", "browser_profile"),
    )
    memory = Memory(cfg.get("memory.db_path", "nova.db"))

    chat_llm = getattr(planner, "llm", None)   # may be a cloud API or local Ollama
    local = _local_ollama(cfg)                 # always-local: embeddings + vision stay on-device

    # semantic memory (RAG): recall facts by meaning. Embeddings stay LOCAL even
    # when chat runs on a cloud API (that data never leaves the machine).
    if local is not None:
        memory.embedder = local.embed
        try:
            memory.reindex_facts()          # backfill any pre-existing facts
        except Exception:
            pass

    # vision-language model: give image/PDF analysis + the operate loop real eyes.
    vision_llm = None
    if local is not None:
        vmodel = cfg.get("brain.vision_model", "qwen2.5vl:3b")
        try:
            if vmodel and local.has_model(vmodel):
                vision_llm = OllamaClient(
                    cfg.get("brain.ollama_url"), vmodel,
                    int(cfg.get("brain.timeout_s", 90)),
                )
                logging.getLogger("nova").info("vision: %s", vmodel)
        except Exception:
            pass

    # live web search (LangSearch) — Sarthi's window to today's internet.
    researcher = None
    if bool(cfg.get("search.enabled", True)):
        try:
            from .brain.researcher import Researcher
            from .connectors.web_search import WebSearchClient
            api_key = cfg.get("search.api_key") or os.getenv("LANGSEARCH_API_KEY")
            client = WebSearchClient(api_key, timeout_s=int(cfg.get("search.timeout_s", 20)))
            researcher = Researcher(
                chat_llm, client, language=cfg.get("assistant.language", "hindi")
            )
            if client.available():
                logging.getLogger("nova").info("web search: LangSearch ready")
        except Exception:
            pass

    pipeline = Pipeline(planner, executor, speaker, memory)
    return ConversationEngine(
        pipeline, chat, speaker,
        wake_word=cfg.get("assistant.wake_word", "hey nova"),
        language=cfg.get("assistant.language", "hindi"),
        vision_llm=vision_llm,
        researcher=researcher,
        stream_replies=bool(cfg.get("brain.stream", True)),
    )


def _make_confirm_fn(speaker: Speaker, transcriber: Transcriber):
    """Voice confirmation for sensitive steps. Safe default: deny without a clear 'yes'."""
    def confirm(step: Step) -> bool:
        speaker.say("This is a sensitive action. Should I proceed?")
        if not transcriber.available:
            speaker.say("I can't confirm by voice yet, so I'll hold off.")
            return False
        reply = (transcriber.transcribe(3.0) or "").lower()
        return any(w in reply for w in ("yes", "yeah", "go ahead", "proceed", "do it"))
    return confirm


def _make_speaker(cfg) -> Speaker:
    return Speaker(
        rate=int(cfg.get("voice.tts.rate", 185)),
        engine=cfg.get("voice.tts.engine", "edge"),
        voice=cfg.get("voice.tts.voice", "hi-IN-SwaraNeural"),
    )


def _make_transcriber(cfg) -> Transcriber:
    return Transcriber(
        cfg.get("voice.stt.model", "base"),
        cfg.get("voice.stt.device", "auto"),
        language=cfg.get("voice.stt.language", "en"),
    )


def run_once(cfg, text: str, dry_run: bool) -> None:
    speaker = _make_speaker(cfg)
    planner, chat = _build_brain(cfg)
    engine = _build_engine(cfg, planner, chat, speaker, dry_run=dry_run)
    engine.address(text)              # explicit one-shot: no wake word needed


def run_chat(cfg) -> None:
    """Text REPL — talk to Nova by typing. Shows her attention state each turn."""
    speaker = _make_speaker(cfg)
    planner, chat = _build_brain(cfg)
    engine = _build_engine(cfg, planner, chat, speaker)
    print("Nova text-chat. Wo abhi SO rahi hai — pehle naam lekar bulao "
          "(jaise: 'nova sun'). 'quit' se bahar.\n")
    while True:
        try:
            line = input(f"[{engine.state.value}] you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in ("quit", "exit"):
            break
        engine.feed(line)
    print("bye")


class Worker(threading.Thread):
    """Drives the ConversationEngine on one thread so side effects/TTS stay serial."""

    def __init__(self, cfg, engine, transcriber, command_q, status_q):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.engine = engine
        self.transcriber = transcriber
        self.command_q = command_q
        self.status_q = status_q

    def run(self) -> None:
        from .ui import LISTEN

        while True:
            item = self.command_q.get()
            if item is None:
                break
            if item is LISTEN:
                self.status_q.put("Sun rahi hoon…")
                text = self.transcriber.listen(
                    end_silence_ms=int(self.cfg.get("voice.stt.end_silence_ms", 700))
                )
                if not text:
                    self.status_q.put("Samajh nahi aaya.")
                    continue
                self.status_q.put(f"Suna: {text}")
                self.engine.feed(text)          # state machine (wake word applies)
            else:
                self.engine.address(item)       # typed box = explicit addressing
            self.status_q.put(f"[{self.engine.state.value}]")


def _start_wake_thread(cfg, transcriber, command_q, status_q) -> None:
    """Optional always-on 'Hey Nova' listener that enqueues a LISTEN on detection."""
    if not bool(cfg.get("wake.enabled", False)):
        return
    from .ui import LISTEN
    from .voice.wake import WakeWord

    wake = WakeWord(
        backend=cfg.get("wake.backend", "keyword"),
        wake_word=cfg.get("assistant.wake_word", "hey nova"),
        transcriber=transcriber,
        chunk_seconds=float(cfg.get("wake.chunk_seconds", 1.5)),
        energy_threshold=float(cfg.get("wake.energy_threshold", 0.012)),
        oww_model=cfg.get("wake.oww_model", "hey_jarvis"),
        threshold=float(cfg.get("wake.threshold", 0.5)),
    )
    if not wake.available:
        status_q.put("Wake word off (needs STT deps or a model).")
        return

    def loop() -> None:
        while True:
            if wake.wait():
                status_q.put("Wake word heard — listening…")
                command_q.put(LISTEN)

    threading.Thread(target=loop, daemon=True).start()
    status_q.put(f"Say '{cfg.get('assistant.wake_word', 'hey nova')}' to activate.")


def run_listen(cfg) -> None:
    """Headless live voice: VAD endpointing mic -> engine.feed().

    No fixed window — it captures while you talk and stops ~0.7s after you go
    quiet, so the reply comes right when your sentence ends. Because speaking is
    blocking, the mic isn't listening while Sarthi talks (no self-echo loop).
    """
    speaker = _make_speaker(cfg)
    planner, chat = _build_brain(cfg)
    transcriber = _make_transcriber(cfg)
    if not transcriber.available:
        print("Mic/STT ready nahi hai. Install: pip install faster-whisper sounddevice")
        return
    engine = _build_engine(cfg, planner, chat, speaker, transcriber=transcriber)
    engine.state = State.ACTIVE          # converse immediately in the live loop

    end_ms = int(cfg.get("voice.stt.end_silence_ms", 700))
    print("Sarthi live — bol ke ruk jao, wo turant jawab degi. (Ctrl+C se bahar)\n")
    try:
        while True:
            text = transcriber.listen(end_silence_ms=end_ms)
            if not text:
                continue
            print("you:", text)
            engine.feed(text)
    except KeyboardInterrupt:
        print("\nbye")


def run_app(cfg) -> None:
    """Launch the web-app UI (FastAPI) in the browser."""
    from .webui.server import run_app as _serve

    planner, chat = _build_brain(cfg)

    def build_engine(speaker):
        return _build_engine(cfg, planner, chat, speaker)

    _serve(cfg, build_engine, lambda: _make_speaker(cfg))


def run_glass(cfg) -> None:      # kept as an alias
    run_app(cfg)


def run_ui(cfg, dry_run: bool) -> None:
    run_app(cfg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nova — voice-first AI OS core")
    parser.add_argument("--text", help="run a single command and exit (no UI)")
    parser.add_argument("--chat", action="store_true", help="text REPL — talk by typing")
    parser.add_argument("--app", action="store_true", help="web-app UI in the browser (default)")
    parser.add_argument("--glass", action="store_true", help="alias for --app")
    parser.add_argument("--listen", action="store_true", help="headless live voice conversation")
    parser.add_argument("--dry-run", action="store_true", help="plan + speak, never touch the OS")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config()
    if args.text:
        run_once(cfg, args.text, args.dry_run)
    elif args.chat:
        run_chat(cfg)
    elif args.listen:
        run_listen(cfg)
    else:                        # default, --app, --glass all launch the web UI
        run_app(cfg)


if __name__ == "__main__":
    main()
