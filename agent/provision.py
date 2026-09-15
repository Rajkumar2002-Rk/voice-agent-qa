"""Create the four agents under test, with every non-prompt setting pinned.

Two Retell LLM objects (naive prompt, hardened prompt) x two transports
(voice web call, chat). `create-chat-agent` accepts the same `llm_id` as
`create-agent`, so each prompt arm is backed by ONE llm object shared by both
channels — same model, same temperature, same tools. The prompt is the only
independent variable, and the channel is the only other axis.

Usage:
    python -m agent.provision --tool-url https://xxx.trycloudflare.com
    python -m agent.provision --tool-url ... --update   # re-push prompt edits
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from harness.retell_client import RetellClient

from .tools import tool_schemas

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "agent" / "prompts"
ENV_PATH = ROOT / ".env"

# ---------------------------------------------------------------------------
# PINNED CONFIG — identical across every arm. Changing anything here
# invalidates comparison with previously committed runs, so it is written into
# each run's manifest.
# ---------------------------------------------------------------------------
PINNED = {
    "model": "gpt-4.1-mini",          # cheap + fast; keeps the ablation inside free credits
    "model_temperature": 0.0,          # minimise run-to-run variance
    "voice_id": "11labs-Adrian",
    "language": "en-US",
    "interruption_sensitivity": 1.0,   # NOT varied — see findings.md, it's a confound
    "enable_backchannel": False,
    "end_call_after_silence_ms": 30000,
    "begin_message": "Thanks for calling Lakeside Family Clinic, this is Robin. How can I help?",
}

ARMS = ("naive", "hardened")


def _prompt_text(arm: str) -> str:
    raw = (PROMPTS / f"{arm}.md").read_text()
    # strip the HTML comment header — it's provenance for humans, not instruction
    return re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()


def _llm_body(arm: str, tool_url: str) -> dict:
    return {
        "model": PINNED["model"],
        "model_temperature": PINNED["model_temperature"],
        "general_prompt": _prompt_text(arm),
        "begin_message": PINNED["begin_message"],
        "start_speaker": "agent",
        "general_tools": tool_schemas(tool_url),
    }


def _voice_agent_body(llm_id: str, arm: str) -> dict:
    return {
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        "agent_name": f"qa-clinic-voice-{arm}",
        "voice_id": PINNED["voice_id"],
        "language": PINNED["language"],
        "interruption_sensitivity": PINNED["interruption_sensitivity"],
        "enable_backchannel": PINNED["enable_backchannel"],
        "end_call_after_silence_ms": PINNED["end_call_after_silence_ms"],
    }


def _chat_agent_body(llm_id: str, arm: str) -> dict:
    return {
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        "agent_name": f"qa-clinic-chat-{arm}",
        "language": PINNED["language"],
    }


def _write_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    seen = set()
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(prog="agent.provision")
    ap.add_argument("--tool-url", required=True,
                    help="public base URL of the clinic server (cloudflared tunnel)")
    ap.add_argument("--update", action="store_true",
                    help="update existing agents in place instead of creating new")
    args = ap.parse_args()

    load_dotenv(ENV_PATH)
    client = RetellClient()
    manifest: dict[str, dict] = {"pinned": PINNED, "tool_url": args.tool_url, "arms": {}}
    env_updates: dict[str, str] = {}

    for arm in ARMS:
        llm_key = f"RETELL_LLM_ID_{arm.upper()}"
        existing_llm = os.getenv(llm_key)

        if args.update and existing_llm:
            llm = client.update_llm(existing_llm, _llm_body(arm, args.tool_url))
            print(f"[{arm}] updated llm {existing_llm}")
        else:
            llm = client.create_llm(_llm_body(arm, args.tool_url))
            print(f"[{arm}] created llm {llm['llm_id']}")
        llm_id = llm["llm_id"]
        env_updates[llm_key] = llm_id

        voice_key = f"RETELL_AGENT_ID_{arm.upper()}"
        chat_key = f"RETELL_CHAT_AGENT_ID_{arm.upper()}"

        if args.update and os.getenv(voice_key):
            va = client.update_agent(os.getenv(voice_key), _voice_agent_body(llm_id, arm))
            print(f"[{arm}] updated voice agent {va['agent_id']}")
        else:
            va = client.create_agent(_voice_agent_body(llm_id, arm))
            print(f"[{arm}] created voice agent {va['agent_id']}")
        env_updates[voice_key] = va["agent_id"]

        if args.update and os.getenv(chat_key):
            ca = client.update_agent(os.getenv(chat_key), _chat_agent_body(llm_id, arm))
            print(f"[{arm}] updated chat agent {ca['agent_id']}")
        else:
            ca = client._req("POST", "/create-chat-agent", json=_chat_agent_body(llm_id, arm))
            print(f"[{arm}] created chat agent {ca['agent_id']}")
        env_updates[chat_key] = ca["agent_id"]

        manifest["arms"][arm] = {
            "llm_id": llm_id,
            "voice_agent_id": va["agent_id"],
            "chat_agent_id": ca["agent_id"],
            "prompt_sha": __import__("hashlib").sha256(
                _prompt_text(arm).encode()).hexdigest()[:16],
        }

    _write_env(env_updates)
    (ROOT / "runs" / "agent_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nwrote agent ids to {ENV_PATH}")
    print("wrote manifest to runs/agent_manifest.json")
    print("\nNOTE: the tunnel URL changes every time cloudflared restarts. "
          "Re-run with --update after restarting it, or the tools will 404.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
