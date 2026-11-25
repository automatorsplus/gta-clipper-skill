"""Ask Claude a question from a script and get JSON back.

    import claude_run
    data = claude_run.ask_json(prompt, files={"sheet.jpg": "/path/to/sheet.jpg"})

Calls the `claude` command line in print mode, so it runs on whatever account your Claude Code is logged in to. No API
key needed. It runs with no MCP servers and no saved session, in an empty temp folder holding only the files you pass,
and only the Read tool when there are files (so Claude can open the contact sheets). It cannot touch anything else.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

CANDIDATES = (os.environ.get("CLAUDE_BIN", ""), os.path.expanduser("~/.local/bin/claude"), "/usr/local/bin/claude",
              "/opt/homebrew/bin/claude")

# Claude's safety filter sometimes flags a normal prompt about game footage; the same prompt usually goes through on a
# second try, so it is asked again, twice.
FLAGGED = re.compile(r"safeguards flagged|legal/aup|usage policy", re.I)
FLAG_TRIES, FLAG_WAIT_S = 3, 20


class ClaudeError(Exception):
    pass


def claude_bin() -> str:
    for c in CANDIDATES:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    found = shutil.which("claude")
    if found:
        return found
    raise ClaudeError("the claude command line is not installed (install Claude Code first)")


def ask(prompt: str, timeout: int = 900, files: dict | None = None) -> dict:
    """_ask_once(), asked again when the safety filter flags a normal prompt."""
    for n in range(1, FLAG_TRIES + 1):
        try:
            return _ask_once(prompt, timeout, files)
        except ClaudeError as e:
            if n == FLAG_TRIES or not FLAGGED.search(str(e)):
                raise
            print("Claude's safety filter flagged the prompt; asking again (%d of %d)" % (n + 1, FLAG_TRIES),
                  file=sys.stderr)
            time.sleep(FLAG_WAIT_S)
    raise ClaudeError("unreachable")


def _ask_once(prompt: str, timeout: int = 900, files: dict | None = None) -> dict:
    """One print-mode turn. Returns Claude Code's JSON envelope (result, is_error, total_cost_usd, ...)."""
    with tempfile.TemporaryDirectory(prefix="gta-clipper-claude-") as empty:
        for name, path in (files or {}).items():
            shutil.copyfile(path, os.path.join(empty, os.path.basename(name)))
        try:
            r = subprocess.run([claude_bin(), "-p", "--output-format", "json", "--tools", "Read" if files else "",
                                "--strict-mcp-config", "--no-session-persistence"],
                               input=prompt, capture_output=True, text=True, timeout=timeout, cwd=empty)
        except subprocess.TimeoutExpired:
            raise ClaudeError("Claude did not answer within %d seconds" % timeout)
    try:
        env = json.loads(r.stdout)
    except ValueError:
        raise ClaudeError("Claude's answer was not readable: %s" % (r.stderr or r.stdout).strip()[-300:])
    if env.get("is_error"):
        raise ClaudeError("Claude returned an error: %s" % str(env.get("result"))[:300])
    return env


def ask_json(prompt: str, timeout: int = 900, files: dict | None = None):
    """ask(), then the JSON object or array inside the answer (a ```json fence is allowed)."""
    return parse_json(str(ask(prompt, timeout, files).get("result") or ""))


def parse_json(text: str):
    """The JSON in an answer: the longest object or array that parses, looked for inside a ```json fence first, then
    in the whole answer."""
    decoder = json.JSONDecoder()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    for body in ([fenced.group(1)] if fenced else []) + [text]:
        best, best_len = None, 0
        for i in [m.start() for m in re.finditer(r"[{\[]", body)][:200]:
            try:
                got, end = decoder.raw_decode(body[i:])
            except ValueError:
                continue
            if isinstance(got, (dict, list)) and end > best_len:
                best, best_len = got, end
        if best is not None and best_len > 2:
            return best
    if not re.search(r"[{\[]", text):
        raise ClaudeError("no JSON in Claude's answer: %s" % text[:300])
    raise ClaudeError("Claude's JSON did not parse: %s" % text[:300])
