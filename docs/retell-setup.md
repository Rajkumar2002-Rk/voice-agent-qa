# Retell account setup — do this before anything else

Everything here is manual and takes ~20 minutes. Nothing in this repo runs against a
live key until you've finished. Costs are covered by Retell's free credits.

---

## 1. Create the account

1. Go to <https://dashboard.retellai.com> and sign up.
2. New accounts get **$10 in free credits** and **20 free concurrent calls** — enough
   for the whole experiment if we keep calls short (the runner enforces this).
3. You do **not** need to add a payment method or buy a phone number. We use web calls
   and the Chat API only.

## 2. Generate an API key

1. Dashboard → **API Keys** (left sidebar, near the bottom).
2. Create a key. It starts with `key_`.
3. Copy it into your local `.env` as `RETELL_API_KEY=`.

> **Never paste the key into chat, a commit, or a screenshot.** `.env` is gitignored.
> If you ever leak one, revoke it in the same dashboard page immediately.

Verify it works:

```bash
make check-key
```

## 3. Install the tunnel (for the clinic tool server)

The agent calls a `check_availability` tool. Retell invokes tools as **webhooks to a
public URL**, so your local clinic server needs to be reachable from the internet.

```bash
brew install cloudflared
```

No cloudflared account is needed — we use a quick tunnel, which prints a temporary
`https://<random>.trycloudflare.com` URL each time you start it.

> **Why bother with a real tool server instead of letting the agent freestyle?**
> Because it makes hallucination *deterministically* measurable. The server logs
> exactly which slots it offered. Any time the agent speaks a specific appointment
> time that the server never returned, that's a hallucination — a fact, not an opinion.
> Without the tool there is no ground truth and you're reduced to asking an LLM to
> guess. See [notes.md](notes.md) for how this decision played out.

## 4. Provision the agents

With the key in `.env` and the tunnel running:

```bash
make tunnel          # terminal 1 — prints the public URL, leave it running
make provision URL=https://<random>.trycloudflare.com   # terminal 2
```

This creates **four** agents and writes their IDs back into your `.env`:

| Agent | Channel | Prompt arm |
|---|---|---|
| `RETELL_AGENT_ID_NAIVE` | voice (web call) | naive |
| `RETELL_AGENT_ID_HARDENED` | voice (web call) | hardened |
| `RETELL_CHAT_AGENT_ID_NAIVE` | text (Chat API) | naive |
| `RETELL_CHAT_AGENT_ID_HARDENED` | text (Chat API) | hardened |

Every non-prompt setting is pinned identical across all four — same model, same voice,
same `interruption_sensitivity`, same temperature. That's what makes it an ablation
rather than an anecdote. The exact pinned config lives in `agent/provision.py` and is
echoed into each run's manifest so the writeup can prove it.

## 5. Smoke test

```bash
make smoke
```

One short text conversation against the naive agent. Costs a fraction of a cent and
confirms the key, the agents, and the tool server are all wired up.

---

## What this setup deliberately does *not* cover

- **No phone number.** We never touch the PSTN. That's a cost decision with real
  consequences for what the results mean — see the caveats in
  [findings.md](findings.md).
- **No production webhook.** `call_analyzed` webhooks would give richer post-call data,
  but they need a stable public URL. We poll `get-call` instead, which returns the same
  transcript and latency fields.
