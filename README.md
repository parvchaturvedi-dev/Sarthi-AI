# Nova — a voice-first AI OS core (Windows desktop slice)

Not a chatbot. Nova listens, **reasons about a plan**, operates the machine, and
**verifies** the result — then confirms by voice. This repo is the first vertical
slice: the Windows desktop agent plus the reusable core (planner, tool protocol,
memory, voice I/O) that every future device will share.

## The one architectural rule

**The LLM never touches the OS.** The brain only emits a structured `Plan`
(`nova/schema.py`); the `Executor` is the sole owner of side effects, and every
step is verified against real window state before the next one runs.

```
utterance ─▶ Planner (LLM) ─▶ Plan(JSON) ─▶ Executor ─▶ tool ─▶ Verify ─▶ speak
                  │ falls back to a rule-based planner if Ollama is offline
```

## Layout

| Path | Role |
|---|---|
| `nova/schema.py` | The brain↔OS contract: `Plan`, `Step`, `Verify` |
| `nova/brain/llm.py` | Ollama client (JSON output, warm-up, availability probe) |
| `nova/brain/planner.py` | LLM planner + offline rule-based fallback |
| `nova/agent/tools.py` + `tools_ext.py` | The **only** code that touches the OS — 24 tools: apps, url, type, keys, focus, clipboard, screenshot, guarded shell, OCR read/click, **volume, reminder, window mgmt, file find/open, YouTube, power (lock/sleep), WhatsApp** |
| `nova/agent/verify.py` | Reads window state back to confirm a step worked |
| `nova/agent/executor.py` | Runs a plan, one verified step at a time |
| `nova/voice/tts.py` | Speech out (pyttsx3 / Windows SAPI5, offline) |
| `nova/voice/stt.py` | Speech in (faster-whisper) |
| `nova/voice/wake.py` | "Hey Nova" wake word (keyword + openwakeword backends) |
| `nova/vision/ocr.py` | Screen OCR (RapidOCR) — read the screen, click text |
| `nova/memory/store.py` | SQLite: contacts, prefs, command history |
| `nova/ui/floating.py` | Always-on-top floating button — no chat window |
| `nova/pipeline.py` | The full lifecycle wired together |
| `nova/main.py` | Entry point + background worker thread |

## Run it

```powershell
# 1. Deps (most are already present). For the mic, add the two STT packages:
pip install faster-whisper sounddevice

# 2. Local brain (optional — it falls back to rules if absent):
ollama serve            # in another terminal
ollama pull qwen2.5:7b-instruct-q4_K_M

# 3a. One-shot, no UI — best for testing:
python -m nova.main --text "open notepad"
python -m nova.main --dry-run --text "search for weather in delhi"   # plan only, no actions

# 3b. Floating widget (voice if the mic is set up, else type a command):
python -m nova.main
```

Config lives in `config.yaml`; override anything in a git-ignored
`config.local.yaml` (e.g. `brain: {provider: rules}` to force offline mode).

## Voice + vision

```powershell
pip install faster-whisper sounddevice openwakeword rapidocr-onnxruntime
```

- **Speech in/out**: verified end to end (TTS→WAV→faster-whisper round-trips text).
- **Wake word** — set `wake.enabled: true` in config. `keyword` backend matches
  "Hey Nova" literally via STT; `openwakeword` is the efficient neural option
  (pretrained phrases; drop a trained `hey_nova.onnx` for the real phrase).
- **Vision** — `read_screen` OCRs the display; `click_text "Send"` finds text on
  screen and clicks it. This is the Screenshot→OCR→Decision→Tap loop.

## Talking to Nova (conversation engine)

Nova has an **attention state machine** so she behaves like a person, not a
macro:

- **SLEEPING** — only her name wakes her (`"Nova, sun"`).
- **ACTIVE** — full conversation: actions *and* questions, no wake word per turn.
- **PAUSED** — say *"ruk ja, main papa se baat kar raha hoon"* and she goes quiet
  even if she hears you, until you call her name again.

Inside a turn she routes: control → rules-first action (instant) → LLM planner →
else a conversational answer. So `"calculator kholo"` acts, `"France ki rajdhani?"`
answers, and she remembers the last few turns (`"aur ek shayari sunao"`).

```powershell
python -m nova.main --chat      # type to talk (start with "nova sun") — try it now
python -m nova.main --listen    # headless live voice conversation
python -m nova.main             # floating widget
```

## Status

Working today: LLM planning (Ollama) + offline rule fallback · 14 verified
desktop/vision tools · window-state verification · STT + TTS · "Hey Nova" wake
word · screen OCR · memory logging · floating UI + worker.

Next: energy-gated continuous listening polish · a trained `hey_nova` model ·
device comms layer (WebSocket) · then the **Android agent** over the same
`Plan` contract.
