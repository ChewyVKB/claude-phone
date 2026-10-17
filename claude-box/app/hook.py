#!/usr/bin/env python3
"""Claude Code hook -> phone callback requests.

Called by Claude Code (see templates/settings.json) as:
    hook.py pretool      PreToolUse: remember what tool Claude is about to use
    hook.py permission   Notification(permission_prompt): ask to ring for approval
    hook.py stop         Stop: ring if Claude ended its turn with a question

Hooks only drop a small JSON request into /spool/requests. The watcher decides
whether to actually ring (quiet hours, mute, rate limits) and does the speech.
Standard library only, always exits 0, never prints to stdout.
"""
import json
import os
import re
import sys
import time
import uuid

SPOOL = os.environ.get("SPOOL_DIR", "/spool")
RING_ON_DONE = os.environ.get("RING_ON_DONE", "false").lower() in ("1", "true", "yes")


def write_json(final_path, data):
    tmp = os.path.join(SPOOL, "tmp", f".{uuid.uuid4().hex}.json")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, final_path)  # atomic: watcher never sees half a file


def request(kind, **fields):
    data = {"kind": kind, "ts": time.time(), **fields}
    name = f"{int(time.time() * 1000)}-{kind}.json"
    write_json(os.path.join(SPOOL, "requests", name), data)


def summarize_tool(name, inp):
    name = name or "a tool"
    if name == "Bash":
        return f"run the command: {inp.get('command', '')}"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        return f"{'write' if name == 'Write' else 'edit'} the file {os.path.basename(path)}"
    if name == "WebFetch":
        host = re.sub(r"^https?://([^/]+).*$", r"\1", inp.get("url", ""))
        return f"fetch a web page from {host}"
    if name.startswith("mcp__"):
        parts = name.split("__")
        return f"use {parts[-1].replace('_', ' ')} from {parts[1]}"
    return f"use {name}"


def last_assistant_text(data):
    text = data.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text
    # Fallback for older Claude Code versions: read the transcript
    path = data.get("transcript_path")
    if not path or not os.path.exists(path):
        return ""
    last = ""
    with open(path, errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list):
                chunk = " ".join(c.get("text", "") for c in content
                                 if isinstance(c, dict) and c.get("type") == "text")
                if chunk.strip():
                    last = chunk
    return last


def clean_for_speech(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)        # code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)                  # inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # links
    text = re.sub(r"^\s*(#+|[-*]|\d+\.)\s+", "", text, flags=re.M)  # headings, bullets
    text = re.sub(r"[*_>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_question(text):
    """Return the question Claude ended on, or None."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S).strip()
    if "?" not in text[-400:]:
        return None
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    for p in reversed(paragraphs):
        if "?" in p:
            q = clean_for_speech(p)
            return q[:350] + ("..." if len(q) > 350 else "")
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    if mode == "pretool":
        write_json(os.path.join(SPOOL, "state", "last_tool.json"), {
            "ts": time.time(),
            "summary": summarize_tool(data.get("tool_name"), data.get("tool_input") or {}),
        })

    elif mode == "permission":
        summary = ""
        try:
            with open(os.path.join(SPOOL, "state", "last_tool.json")) as f:
                last = json.load(f)
            if time.time() - last.get("ts", 0) < 120:
                summary = last.get("summary", "")
        except Exception:
            pass
        request("permission", message=data.get("message", ""), summary=summary)

    elif mode == "stop":
        if data.get("stop_hook_active"):
            return
        text = last_assistant_text(data)
        question = extract_question(text)
        if question:
            request("question", text=question)
        elif RING_ON_DONE and text.strip():
            first = clean_for_speech(text)
            first = re.split(r"(?<=[.!])\s", first, maxsplit=1)[0][:200]
            request("done", text=first)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a broken hook must never break Claude Code
        print(f"claude-phone hook error: {e}", file=sys.stderr)
    sys.exit(0)
