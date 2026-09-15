"""Render the scripted callers to committed WAV fixtures.

Run once; the WAVs go into the repo. Every subsequent run replays byte-identical
audio, so the caller side of the experiment is fully deterministic and anyone
who clones this reproduces the same stimulus. That matters more than realism:
a caller that says something slightly different each run makes the ablation
unfalsifiable.

Usage:
    python -m harness.tts build          # render anything missing
    python -m harness.tts build --force  # re-render everything
    python -m harness.tts noise          # (re)build the noise beds
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .loader import SCENARIO_DIR, load_scenarios

# Without this, TTS_PROVIDER and OPENAI_API_KEY from .env are invisible and the
# builder silently falls back to defaults. Every entrypoint must load .env itself.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "audio"
FIXTURES.mkdir(parents=True, exist_ok=True)
MANIFEST = FIXTURES / "manifest.yaml"

TARGET_RATE = 48000

# Leading/trailing silence around every caller clip.
#
# Without it a fixture starts at full amplitude on sample zero, which is nothing
# like human speech onset and gives the far end's voice-activity detector no
# ramp-up. Short clips suffered worst: "Four PM." (0.50s, hard attack)
# transcribed as "For", losing the time entirely. See B19 in docs/notes.md —
# that result is confounded precisely because this padding was missing.
PAD_MS = 250


def _ffmpeg(*args: str) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[:400]}")


def _to_wav48(src: Path, dst: Path) -> None:
    """Resample to 48k mono PCM and pad with silence at both ends."""
    pad = PAD_MS / 1000.0
    _ffmpeg(
        "-i", str(src),
        "-af", f"adelay={PAD_MS}|{PAD_MS},apad=pad_dur={pad}",
        "-ar", str(TARGET_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    )


class SilentRender(RuntimeError):
    pass


def _peak_dbfs(path: Path) -> float:
    """Peak level of a rendered clip, via ffmpeg's volumedetect."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else -999.0


# Healthy TTS output peaks around -7 dBFS. Two clips came back near-silent
# (-46 dB) and were played into live calls as nothing at all — the agent heard
# no answer, looped, and the scenario scored as an agent failure. Validate every
# render; a fixture that cannot be heard is worse than a missing one, because a
# missing one fails loudly.
MIN_PEAK_DBFS = -20.0


def _verify(path: Path, text: str) -> None:
    if not path.exists() or path.stat().st_size < 2000:
        raise SilentRender(f"{path.name}: file missing or too small for {text!r}")
    peak = _peak_dbfs(path)
    if peak < MIN_PEAK_DBFS:
        raise SilentRender(
            f"{path.name}: peak {peak:.1f} dBFS is below {MIN_PEAK_DBFS} dBFS — "
            f"the render of {text!r} is effectively silent"
        )


def _synthesize(text: str, dst: Path, voice: str) -> None:
    provider = os.getenv("TTS_PROVIDER", "openai").lower()
    if provider == "macos":
        aiff = dst.with_suffix(".aiff")
        subprocess.run(["say", "-v", voice or "Samantha", "-o", str(aiff), text],
                       check=True)
        _to_wav48(aiff, dst)
        aiff.unlink(missing_ok=True)
        return

    if provider == "openai":
        try:
            from openai import OpenAI
        except ImportError as e:
            raise SystemExit(
                "openai package missing. uv pip install -e '.[judge]'  "
                "(or set TTS_PROVIDER=macos for a free offline fallback)"
            ) from e
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY not set (or use TTS_PROVIDER=macos)")
        client = OpenAI()
        tmp = dst.with_suffix(".mp3")
        with client.audio.speech.with_streaming_response.create(
            model="tts-1", voice=voice or "alloy", input=text,
        ) as resp:
            resp.stream_to_file(tmp)
        _to_wav48(tmp, dst)
        tmp.unlink(missing_ok=True)
        return

    raise SystemExit(f"unknown TTS_PROVIDER={provider!r}")


def build(force: bool = False) -> None:
    voice = os.getenv("TTS_VOICE", "alloy")
    manifest: dict[str, dict] = {}
    rendered = skipped = 0

    for sc in load_scenarios():
        path = SCENARIO_DIR / f"{sc.id}.yaml"
        raw = yaml.safe_load(path.read_text())
        changed = False

        for i, turn in enumerate(sc.turns):
            if not turn.say:
                continue
            name = f"{sc.id}_t{i:02d}.wav"
            dst = FIXTURES / name
            digest = hashlib.sha256(f"{voice}|{turn.say}".encode()).hexdigest()[:12]

            if dst.exists() and not force and MANIFEST.exists():
                prev = yaml.safe_load(MANIFEST.read_text()) or {}
                if prev.get(name, {}).get("digest") == digest:
                    manifest[name] = prev[name]
                    skipped += 1
                    raw["turns"][i]["audio_file"] = name
                    changed = True
                    continue

            print(f"  rendering {name}: {turn.say[:60]!r}")
            for attempt in range(1, 6):
                _synthesize(turn.say, dst, voice)
                try:
                    _verify(dst, turn.say)
                    break
                except SilentRender as e:
                    print(f"    attempt {attempt}: {e}")
                    if attempt == 5:
                        raise SystemExit(
                            f"TTS produced silent audio for {turn.say!r} five "
                            f"times. Refusing to ship a fixture that cannot "
                            f"be heard."
                        ) from e
            manifest[name] = {"text": turn.say, "voice": voice, "digest": digest}
            raw["turns"][i]["audio_file"] = name
            rendered += 1
            changed = True

        if changed:
            path.write_text(yaml.safe_dump(raw, sort_keys=False, width=100))

    MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=True))
    print(f"\n{rendered} rendered, {skipped} unchanged -> {FIXTURES}")


def noise() -> None:
    """Noise beds, generated procedurally so they're reproducible and license-free."""
    beds = {
        # pink noise ~ the spectral shape of room/cafe rumble
        "noise_cafe_babble.wav": [
            "-f", "lavfi", "-i", f"anoisesrc=color=pink:r={TARGET_RATE}:d=12",
            "-af", "volume=-12dB",
        ],
        # a band-limited warble standing in for a second speaker talking over
        "noise_second_voice.wav": [
            "-f", "lavfi",
            "-i", f"anoisesrc=color=brown:r={TARGET_RATE}:d=12",
            "-af", "bandpass=f=1200:width_type=h:w=900,tremolo=f=5.5:d=0.7,volume=-9dB",
        ],
    }
    for name, args in beds.items():
        dst = FIXTURES / name
        _ffmpeg(*args, "-ac", "1", "-c:a", "pcm_s16le", str(dst))
        print(f"  built {name}")
    print("\nNote: these are synthetic stand-ins, not recordings of real cafes or "
          "real overlapping speech.\nThey degrade the signal in a controlled, "
          "reproducible way; they do not reproduce\nthe specific ways real "
          "room noise defeats real STT. Stated as a caveat in findings.md.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="harness.tts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--force", action="store_true")
    sub.add_parser("noise")
    a = ap.parse_args()
    if a.cmd == "build":
        build(force=a.force)
    else:
        noise()


if __name__ == "__main__":
    sys.exit(main())
