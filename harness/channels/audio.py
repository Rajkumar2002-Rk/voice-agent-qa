"""Voice channel — real WebRTC web call driven from headless Chromium.

WHY A BROWSER AT ALL
--------------------
Retell web calls use a custom WebRTC "gateway" transport. `create-web-call`
returns a call_id, an access_token and ICE servers; signalling then goes through
an internal `/webrtc-proxy/{call_id}` endpoint. There is no documented
server-side way to join. Two options existed:

  (a) reimplement that signalling in Python with aiortc — depends on an
      undocumented internal endpoint that can change without notice;
  (b) run the real, supported SDK in a real browser and feed it a synthetic
      microphone.

We chose (b). It uses only public API surface, so it keeps working when Retell
changes its internals, and the audio path is genuinely real: Opus over WebRTC,
real jitter buffer, real endpointing, real barge-in.

WHAT IT STILL ISN'T
-------------------
It is not telephony. See the caveats section of findings.md — no 8kHz codec, no
PSTN jitter, no carrier packet loss.

STATUS: this module is written against the documented SDK surface but has NOT
been executed against a live Retell account in this repo's history. The first
real run should be `make smoke-voice`, and the SDK entrypoint is the most
likely thing to need adjustment (see `page/harness.html`).
"""

from __future__ import annotations

import base64
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..retell_client import RetellClient
from ..schema import Scenario
from .base import captured_slots_from_events, flatten_transcript

PAGE = Path(__file__).parent / "page" / "harness.html"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "audio"


class AudioChannelUnavailable(RuntimeError):
    pass


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise AudioChannelUnavailable(
            "playwright is not installed. Run:  uv pip install -e '.[audio]' "
            "&& python -m playwright install chromium"
        ) from e
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def run_voice_scenario(
    client: RetellClient,
    agent_id: str,
    scenario: Scenario,
    *,
    headless: bool = True,
    max_call_seconds: int = 120,
) -> dict[str, Any]:
    sync_playwright = _require_playwright()
    started = datetime.now(UTC).isoformat()

    call = client.create_web_call(agent_id, metadata={"scenario_id": scenario.id})
    call_id = call["call_id"]
    access_token = call["access_token"]

    driver_log: list[dict[str, Any]] = []
    deadline = time.time() + max_call_seconds

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-ui-for-media-stream",
                "--disable-features=AudioServiceOutOfProcess",
            ],
        )
        ctx = browser.new_context(permissions=["microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: driver_log.append(
            {"t": time.time(), "console": m.text[:300]}))
        page.goto(PAGE.as_uri())

        # preload every clip this scenario needs
        for i, turn in enumerate(scenario.turns):
            if turn.audio_file:
                p = FIXTURES / turn.audio_file
                if not p.exists():
                    raise FileNotFoundError(
                        f"missing audio fixture {p}. Run: python -m harness.tts build"
                    )
                page.evaluate("([id, b64]) => window.__qa_loadClip(id, b64)",
                              [f"turn{i}", _b64(p)])
            if turn.noise:
                np_ = FIXTURES / f"noise_{turn.noise}.wav"
                if np_.exists():
                    page.evaluate("([id, b64]) => window.__qa_loadClip(id, b64)",
                                  [f"noise_{turn.noise}", _b64(np_)])

        res = page.evaluate(
            "(cfg) => window.__qa_start(cfg)",
            {"accessToken": access_token, "callId": call_id},
        )
        if not res.get("ok"):
            browser.close()
            raise RuntimeError(f"web call failed to start: {res.get('error')}")

        # ---- drive the scripted caller ---------------------------------
        for i, turn in enumerate(scenario.turns):
            if time.time() > deadline:
                driver_log.append({"t": time.time(), "note": "max_call_seconds hit"})
                break

            if turn.silence_ms:
                driver_log.append({"t": time.time(), "turn": i,
                                   "action": "silence", "ms": turn.silence_ms})
                page.wait_for_timeout(turn.silence_ms)
                continue

            if turn.interrupt_after_ms is not None:
                # barge-in: wait for the agent to START, then cut in mid-sentence
                page.evaluate("(ms) => window.__qa_waitAgentStart(ms)", 15000)
                page.wait_for_timeout(turn.interrupt_after_ms)
                driver_log.append({"t": time.time(), "turn": i, "action": "barge_in",
                                   "after_ms": turn.interrupt_after_ms})
            elif turn.wait_for_agent:
                page.evaluate("(ms) => window.__qa_waitAgentDone(ms)", 25000)

            page.evaluate(
                "([id, opts]) => window.__qa_play(id, opts)",
                [f"turn{i}", {"noiseId": f"noise_{turn.noise}" if turn.noise else None}],
            )
            driver_log.append({"t": time.time(), "turn": i, "action": "spoke",
                               "said": turn.say})

        # let the agent finish its last turn before hanging up
        page.evaluate("(ms) => window.__qa_waitAgentDone(ms)", 20000)
        page_state = page.evaluate("() => window.__qa_state()")
        page.evaluate("() => window.__qa_stop()")
        page.wait_for_timeout(1000)
        browser.close()

    call_final = client.wait_for_call_end(call_id)
    events = flatten_transcript(call_final.get("transcript_with_tool_calls") or [])

    return {
        "channel": "voice",
        "call_id": call_id,
        "started_at": started,
        "ended_at": datetime.now(UTC).isoformat(),
        "events": events,
        "captured_slots": captured_slots_from_events(events),
        "raw": call_final,
        "driver_log": driver_log,
        "page_state": {k: v for k, v in (page_state or {}).items() if k != "events"},
        "retell_latency": call_final.get("latency"),
        "disconnection_reason": call_final.get("disconnection_reason"),
    }
