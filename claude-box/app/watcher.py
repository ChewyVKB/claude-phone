#!/usr/bin/env python3
"""Claude Phone watcher: the glue between Asterisk and Claude Code.

  /spool/in/prompt-*.wav16   your recorded prompt     -> Whisper -> typed into tmux
  /spool/in/reply-*.wav16    your answer on a callback -> Whisper -> typed into tmux
  /spool/in/perm-*.txt       keypad choice (1/2)       -> Enter / Escape in tmux
  /spool/requests/*.json     from Claude Code hooks    -> Piper speech + call file -> phone rings
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
import wave

SPOOL = os.environ.get("SPOOL_DIR", "/spool")
PHONE_EXT = os.environ.get("PHONE_EXT", "100")
TMUX_TARGET = os.environ.get("TMUX_TARGET", "claude")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small.en")
WHISPER_HINT = os.environ.get("WHISPER_HINT", "") or None
PIPER_VOICE = os.environ.get("PIPER_VOICE", "en_US-lessac-medium")
VOICES_DIR = os.environ.get("VOICES_DIR", "/data/voices")
QUIET_HOURS = os.environ.get("QUIET_HOURS", "22-7")
MIN_CALL_GAP = int(os.environ.get("MIN_CALL_GAP", "60"))
CALLBACK_MODE = os.environ.get("CALLBACK_MODE", "phone")
PHONE_SESSION_HOURS = float(os.environ.get("PHONE_SESSION_HOURS", "3"))
PERMISSION_PATTERN = os.environ.get("PERMISSION_PATTERN", "Do you want to")

# Whisper likes to "hear" these in silence or noise
HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye", "okay", "uh", "um"}

D = {name: os.path.join(SPOOL, name) for name in ("in", "tmp", "tts", "outgoing", "state", "requests")}

_whisper = None
_voice = None
_last_call = 0.0


def log(msg):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# ---------------------------------------------------------------- state helpers
def state_path(name):
    return os.path.join(D["state"], name)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    tmp = os.path.join(D["tmp"], f".{uuid.uuid4().hex}")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


# ---------------------------------------------------------------- tmux
def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def screen_text():
    return tmux("capture-pane", "-p", "-t", TMUX_TARGET, "-S", "-40").stdout


def permission_dialog_open():
    return PERMISSION_PATTERN.lower() in screen_text().lower()


def flash(msg):
    """Brief message in the tmux status line, so you see it in the terminal/browser."""
    tmux("display-message", "-t", TMUX_TARGET, "-d", "4000", f"📞 {msg}")


def type_prompt(text):
    tmux("send-keys", "-t", TMUX_TARGET, "-l", "--", text)
    time.sleep(0.4)  # let the TUI take the text before Enter
    tmux("send-keys", "-t", TMUX_TARGET, "Enter")


# ---------------------------------------------------------------- speech
def whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        log(f"Loading Whisper model {WHISPER_MODEL} (first run downloads it)...")
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def transcribe(path):
    segments, _ = whisper().transcribe(
        path, language="en", beam_size=5, vad_filter=True, initial_prompt=WHISPER_HINT)
    return " ".join(s.text.strip() for s in segments).strip()


def voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice
        model = os.path.join(VOICES_DIR, f"{PIPER_VOICE}.onnx")
        if not os.path.exists(model):
            log(f"Downloading Piper voice {PIPER_VOICE}...")
            subprocess.run(["python", "-m", "piper.download_voices", PIPER_VOICE,
                            "--download-dir", VOICES_DIR], check=True)
        _voice = PiperVoice.load(model)
    return _voice


def speak_to_file(text, name):
    """Render text to /spool/tts/<name>.wav as 8 kHz mono, which Asterisk plays natively."""
    final = os.path.join(D["tts"], f"{name}.wav")
    with tempfile.TemporaryDirectory(dir=D["tmp"]) as td:
        raw = os.path.join(td, "raw.wav")
        with wave.open(raw, "wb") as wf:
            voice().synthesize_wav(text, wf)
        out = os.path.join(td, "out.wav")
        subprocess.run(["sox", raw, "-r", "8000", "-c", "1", "-b", "16", out], check=True)
        os.replace(out, final)
    return final


def make_static_prompts():
    beep = os.path.join(D["tts"], "beep.wav")
    if not os.path.exists(beep):
        subprocess.run(["sox", "-n", "-r", "8000", "-c", "1", "-b", "16", beep,
                        "synth", "0.25", "sine", "1000", "vol", "0.5"], check=True)
    phrases = {
        "approved": "Approved.",
        "denied": "Denied.",
        "nochoice": "No choice made. Claude is still waiting at the keyboard.",
        "muted": "Claude callbacks are muted.",
        "unmuted": "Claude callbacks are back on.",
    }
    for name, text in phrases.items():
        if not os.path.exists(os.path.join(D["tts"], f"{name}.wav")):
            speak_to_file(text, name)


# ---------------------------------------------------------------- callback rules
def in_quiet_hours(now=None):
    if not QUIET_HOURS.strip():
        return False
    start, end = (int(x) for x in QUIET_HOURS.split("-"))
    h = (now or dt.datetime.now()).hour
    return start <= h < end if start <= end else (h >= start or h < end)


def why_not_ring(kind, now_ts=None):
    """Return a reason string if we should NOT ring, else None."""
    now_ts = now_ts or time.time()
    if os.path.exists(state_path("muted")):
        return "callbacks muted (*26)"
    if CALLBACK_MODE == "phone":
        last_phone = (read_json(state_path("last_phone_prompt.json"), {}) or {}).get("ts", 0)
        if now_ts - last_phone > PHONE_SESSION_HOURS * 3600:
            return "no phone prompt recently (CALLBACK_MODE=phone)"
    if in_quiet_hours():
        return "quiet hours"
    gap = 10 if kind == "permission" else MIN_CALL_GAP
    if now_ts - _last_call < gap:
        return f"rang less than {gap}s ago"
    return None


def callback_script(req):
    kind = req.get("kind")
    if kind == "permission":
        what = req.get("summary") or req.get("message") or "do something"
        what = what[:200]
        return ("Claude: approve?",
                f"Claude needs permission to {what}. Press 1 to allow, or 2 to deny.")
    if kind == "question":
        return ("Claude: question",
                f"Claude has a question. {req.get('text', '')} Answer after the beep, then hang up.")
    if kind == "done":
        return ("Claude: done", f"Claude is finished. {req.get('text', '')}")
    return None


def place_call(callid, kind, caller_name):
    call = (
        f"Channel: PJSIP/{PHONE_EXT}\n"
        f"CallerID: \"{caller_name}\" <2525>\n"
        "MaxRetries: 0\n"
        "WaitTime: 30\n"
        "Context: claude-callback\n"
        "Extension: s\n"
        "Priority: 1\n"
        f"Setvar: CALLID={callid}\n"
        f"Setvar: CALLKIND={kind}\n"
        "Archive: no\n"
    )
    tmp = os.path.join(D["tmp"], f"{callid}.call")
    with open(tmp, "w") as f:
        f.write(call)
    os.replace(tmp, os.path.join(D["outgoing"], f"{callid}.call"))  # same filesystem: atomic


def handle_request(req):
    global _last_call
    kind = req.get("kind")
    script = callback_script(req)
    if not script:
        return
    reason = why_not_ring(kind)
    if reason:
        log(f"Not ringing for {kind}: {reason}")
        return
    caller_name, text = script
    callid = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
    speak_to_file(text, callid)
    write_json(state_path("pending.json"), {"callid": callid, "kind": kind, "ts": time.time()})
    place_call(callid, kind, caller_name)
    _last_call = time.time()
    log(f"Ringing ext {PHONE_EXT} ({kind}): {text[:120]}")
    flash(f"Calling your phone: {caller_name}")


# ---------------------------------------------------------------- incoming from phone
def handle_recording(path):
    text = transcribe(path)
    if text.lower().strip(" .,!?") in HALLUCINATIONS:
        log(f"Heard nothing usable in {os.path.basename(path)}")
        flash("Didn't catch that. Call again.")
        return
    if permission_dialog_open():
        log(f"Permission dialog is open, NOT typing: {text}")
        flash("Claude is waiting on a permission prompt. Answer that first.")
        return
    log(f"Heard: {text}")
    type_prompt(f"[phone] {text}")
    write_json(state_path("last_phone_prompt.json"), {"ts": time.time(), "text": text})
    if os.path.basename(path).startswith("reply-"):
        try:
            os.remove(state_path("pending.json"))
        except FileNotFoundError:
            pass


def handle_permission_choice(path):
    callid = os.path.basename(path)[len("perm-"):-len(".txt")]
    with open(path) as f:
        choice = f.read().strip()
    pending = read_json(state_path("pending.json"), {}) or {}
    if pending.get("callid") != callid or time.time() - pending.get("ts", 0) > 600:
        log(f"Ignoring stale keypad choice for call {callid}")
        return
    if not permission_dialog_open():
        log("Keypad choice arrived but no permission dialog is open (already answered?)")
        return
    if choice == "1":
        tmux("send-keys", "-t", TMUX_TARGET, "Enter")   # default option is "Yes"
        log("Permission APPROVED from phone")
        flash("Approved from phone")
    else:
        tmux("send-keys", "-t", TMUX_TARGET, "Escape")  # Esc = no
        log("Permission DENIED from phone")
        flash("Denied from phone")
    os.remove(state_path("pending.json"))


# ---------------------------------------------------------------- main loop
def cleanup(max_age=3600):
    keep = {"beep", "approved", "denied", "nochoice", "muted", "unmuted"}
    for f in glob.glob(os.path.join(D["tts"], "*.wav")):
        if os.path.splitext(os.path.basename(f))[0] not in keep and time.time() - os.path.getmtime(f) > max_age:
            os.remove(f)


def process_once():
    for path in sorted(glob.glob(os.path.join(D["requests"], "*.json"))):
        req = read_json(path)
        os.remove(path)
        if req:
            try:
                handle_request(req)
            except Exception as e:
                log(f"Callback failed: {e}")
    for path in sorted(glob.glob(os.path.join(D["in"], "*"))):
        name = os.path.basename(path)
        try:
            if name.startswith(("prompt-", "reply-")) and name.endswith(".wav16"):
                handle_recording(path)
            elif name.startswith("perm-") and name.endswith(".txt"):
                handle_permission_choice(path)
        except Exception as e:
            log(f"Failed on {name}: {e}")
        finally:
            if os.path.exists(path):
                os.remove(path)


def main():
    for d in D.values():
        os.makedirs(d, exist_ok=True)
    log("Claude Phone watcher starting")
    make_static_prompts()
    whisper()  # load now so the first call isn't slow
    log(f"Ready. Dial 2525 from ext {PHONE_EXT} to talk to Claude.")
    last_cleanup = 0
    while True:
        process_once()
        if time.time() - last_cleanup > 600:
            cleanup()
            last_cleanup = time.time()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
