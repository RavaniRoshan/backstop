# Backstop demo — step by step

Watch the live dashboard reproduce five real production failures:

1. **The $10,000 Overnight** — one customer's agent loop burns $10k overnight on DeepInfra
2. **The 11-Day Ping-Pong** — two agents recurse for 11 days, every health check green — $47k on Anthropic
3. **The Thundering Herd** — fifty workflows hit a self-hosted vLLM server returning 429s
4. **The $47,000 RAG Bot** — eight 500-token chunks retrieved for every question on DeepInfra
5. **The $50,000 Unattributed Bill** — thirty-five teams on Amazon Bedrock, $50k/month nobody can attribute

No API key. No network. No bill. The traffic is simulated; the rates, token counts and prices are real.

## What you need

- Python 3.10 or newer
- This repository checked out
- Nothing else — the demo installs nothing and writes nothing outside its own `out/` folder

## Step 1 — open a terminal in the repo

```bash
cd /home/shiva/projects/backstop
```

(Adjust the path to wherever you cloned the repo.)

## Step 2 — see what's available

```bash
python demos/real_world/run.py --list
```

You will see five scenarios and every endpoint kind Backstop supports:

```
Scenarios
─────────
  noisy-neighbour    The $10,000 Overnight
  agent-loop         The 11-Day Ping-Pong
  retry-storm        The Thundering Herd
  rag-peak           The $47,000 RAG Bot
  cloud-gateway      The $50,000 Unattributed Bill

The four kinds of server
────────────────────────
  the provider's own API    OpenAI · Anthropic
  inference servers you run vLLM · SGLang · Ollama · llama.cpp · TGI · LM Studio · Docker Model Runner
  managed inference         DeepInfra · Together AI · Fireworks · OpenRouter · Groq · Cerebras · ...
  cloud gateways            Amazon Bedrock · Azure OpenAI · Google Vertex AI
```

## Step 3 — run the headline scenario

```bash
python demos/real_world/run.py --scenario noisy-neighbour
```

This does four things:

1. Starts the dashboard on `http://127.0.0.1:8787/`
2. Drives simulated traffic against a mock provider (no key, no network)
3. Prints the result: which tenant got cut off, how much it spent, how much would have been spent without the guardrail
4. Stops automatically after 40 seconds

While it runs, open the dashboard in your browser:

```
http://127.0.0.1:8787/
```

Look at:
- **Tenants** — the looping tenant's cap is gone; the other two are untouched
- **Enforcement events** — `budget_exceeded` denials, one per blocked request
- **Spend prevented** — the calls the guardrail stopped

## Step 4 — run all five scenarios (recommended)

```bash
python demos/real_world/run.py --all --duration 10 --speed 2
```

This runs every scenario back-to-back on the same dashboard URL. Each takes about 10 seconds (shortened by `--duration 10`, played twice as fast with `--speed 2`). The URL stays `http://127.0.0.1:8787/` the whole time.

## Step 5 — stop it

Each scenario stops on its own. To cancel mid-run, press **Ctrl-C**.

## Optional variations

| What you want | Command |
|---|---|
| One specific scenario | `python demos/real_world/run.py --scenario retry-storm` |
| Shorter run | `python demos/real_world/run.py --scenario rag-peak --duration 8` |
| Faster replay | `python demos/real_world/run.py --all --speed 4` |
| See all scenarios | `python demos/real_world/run.py --list` |

## Run against a real provider (optional)

The demo is designed to need nothing. If you want real traffic instead of the mock:

```bash
export DEEPINFRA_API_KEY=your-key-here
python demos/real_world/run.py --scenario noisy-neighbour --live --duration 8 --speed 3
```

This spends real money at the scenario's rate — start small.

## Verify it works (optional)

The repo has a test that keeps the demo honest:

```bash
python -m pytest tests/test_real_world_demo.py -q
```

It checks that every scenario runs, every event is priced, and the guardrail actually fires.

## Where the numbers live

Each run writes a ledger to:

```
demos/real_world/out/<scenario>/ledger.jsonl
```

Open it to see the per-request cost — that's what the dashboard draws.

## If anything fails

- **Port already in use:** the demo tries the next free port automatically; the printed dashboard URL tells you which one.
- **No output:** the first scenario takes about 10 seconds before anything prints — it is starting the dashboard and driving traffic.
- **Tests fail:** run `python -m pytest -q -m "not perf"` from the repo root; `demos/` is not part of the published wheel, so it never breaks an install.

That's it — five commands, no setup, and you have watched a production failure get stopped by a guardrail you can name.