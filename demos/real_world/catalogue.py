"""The four kinds of server, and the real situations Backstop has to survive.

Every number in here is either quoted from a source or derived from a quoted
rate, and the source is next to it. The scenarios are the point of the demo:
a guardrail that is only ever tested against a synthetic load generator
proves nothing, so each of these reproduces a documented production
failure, at the parameters that failure actually had.

The prices are DeepInfra's own, from deepinfra.com/pricing, checked on
2026-10-22. A price that is wrong here is wrong in the demo in front of an
instructor, so the file that carries them is ``prices.json`` — the same
mechanism an operator uses, a user price catalog layered over the bundled
one — and not a constant in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: The four kinds of server a production LLM application can call. The wire
#: protocol is the integration: there is no per-provider adapter, and the
#: controls are the same for every row.
PROVIDER_API = "provider"
SELF_HOSTED = "self-hosted"
MANAGED = "managed"
GATEWAY = "gateway"

KIND_LABEL = {
    PROVIDER_API: "the provider's own API",
    SELF_HOSTED: "inference servers you run",
    MANAGED: "managed inference",
    GATEWAY: "cloud gateways",
}


@dataclass(frozen=True)
class Endpoint:
    """One inference endpoint, and what it costs.

    ``input_per_mtok_usd`` and ``output_per_mtok_usd`` are filled into
    ``prices.json``; they are repeated here only so ``--list`` can print the
    rate card without opening the catalog.
    """

    key: str
    kind: str
    label: str
    base_url: str
    model: str
    #: The wire protocol the endpoint speaks. Everything in the matrix but
    #: Anthropic speaks the OpenAI shape; Anthropic has its own.
    protocol: str
    input_per_mtok_usd: str
    output_per_mtok_usd: str
    api_key_env: str | None
    latency_ms: tuple[float, float]
    price_source: str
    note: str = ""


#: Every endpoint in the matrix, whether or not a scenario drives it. The
#: demo prints this so the instructor can see the whole landscape, not just
#: the three the scenarios happen to touch.
ENDPOINTS: dict[str, Endpoint] = {
    # --- 01. the provider's own API. These speak their own protocol, and the
    # bundled price catalog already prices their models.
    "openai": Endpoint(
        key="openai", kind=PROVIDER_API, label="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-5.6-luna",
        protocol="openai",
        input_per_mtok_usd="0.20", output_per_mtok_usd="1.20",
        api_key_env="OPENAI_API_KEY",
        latency_ms=(420, 900),
        price_source="bundled catalog",
        note="Its own endpoint and its own protocol.",
    ),
    "anthropic": Endpoint(
        key="anthropic", kind=PROVIDER_API, label="Anthropic",
        base_url="https://api.anthropic.com",
        model="claude-sonnet-5",
        protocol="anthropic",
        input_per_mtok_usd="2.00", output_per_mtok_usd="10.00",
        api_key_env="ANTHROPIC_API_KEY",
        latency_ms=(600, 1400),
        price_source="bundled catalog",
        note="Its own endpoint and its own protocol.",
    ),
    # --- 02. inference servers you run. They speak an OpenAI-compatible
    # endpoint, and there is no price until you file one.
    "vllm": Endpoint(
        key="vllm", kind=SELF_HOSTED, label="vLLM",
        base_url="http://localhost:8000/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env=None,
        latency_ms=(40, 110),
        price_source="DeepInfRA rate for the same model",
        note="Continuous batching. One tenant can starve the KV cache.",
    ),
    "sglang": Endpoint(
        key="sglang", kind=SELF_HOSTED, label="SGLang",
        base_url="http://localhost:30000/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(25, 70),
        price_source="DeepInfRA rate for the same model",
    ),
    "ollama": Endpoint(
        key="ollama", kind=SELF_HOSTED, label="Ollama",
        base_url="http://localhost:11434/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(20, 60),
        price_source="DeepInfRA rate for the same model",
    ),
    "llama_cpp": Endpoint(
        key="llama_cpp", kind=SELF_HOSTED, label="llama.cpp",
        base_url="http://localhost:9931/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(30, 90),
        price_source="DeepInfRA rate for the same model",
        note="The default port is 9931, not 8080.",
    ),
    "tgi": Endpoint(
        key="tgi", kind=SELF_HOSTED, label="Text Generation Inference",
        base_url="http://localhost:8080/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(30, 90),
        price_source="DeepInfRA rate for the same model",
    ),
    "lmstudio": Endpoint(
        key="lmstudio", kind=SELF_HOSTED, label="LM Studio",
        base_url="http://localhost:1234/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(25, 80),
        price_source="DeepInfRA rate for the same model",
    ),
    "docker_model_runner": Endpoint(
        key="docker_model_runner", kind=SELF_HOSTED, label="Docker Model Runner",
        base_url="http://model-runner.docker.internal/engines/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env=None, latency_ms=(30, 90),
        price_source="DeepInfRA rate for the same model",
    ),
    # --- 03. managed inference. OpenAI-compatible, no price until you file one.
    "deepinfra": Endpoint(
        key="deepinfra", kind=MANAGED, label="DeepInfra",
        base_url="https://api.deepinfra.com/v1/openai",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="DEEPINFRA_API_KEY",
        latency_ms=(45, 95),
        price_source="https://deepinfra.com/pricing (2026-10-22)",
        note=(
            "One base URL, one key, one model name changed. It also has a "
            "service_tier: priority costs +50%, flex −20%, batch −20%."
        ),
    ),
    "deepinfra_flash": Endpoint(
        key="deepinfra_flash", kind=MANAGED, label="DeepInfra",
        base_url="https://api.deepinfra.com/v1/openai",
        model="deepseek-ai/DeepSeek-V4-Flash-0731",
        protocol="openai",
        input_per_mtok_usd="0.06", output_per_mtok_usd="0.18",
        api_key_env="DEEPINFRA_API_KEY",
        latency_ms=(30, 70),
        price_source="https://deepinfra.com/pricing (2026-10-22)",
        note="Its cheapest frontier-class model.",
    ),
    "together": Endpoint(
        key="together", kind=MANAGED, label="Together AI",
        base_url="https://api.together.ai/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="TOGETHER_API_KEY",
        latency_ms=(50, 110),
        price_source="DeepInfRA rate for the same model",
    ),
    "fireworks": Endpoint(
        key="fireworks", kind=MANAGED, label="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="FIREWORKS_API_KEY",
        latency_ms=(40, 95),
        price_source="DeepInfRA rate for the same model",
    ),
    "openrouter": Endpoint(
        key="openrouter", kind=MANAGED, label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="OPENROUTER_API_KEY",
        latency_ms=(60, 140),
        price_source="DeepInfRA rate for the same model",
        note="Routes to whichever provider is cheapest — so your cost can change mid-flight.",
    ),
    "groq": Endpoint(
        key="groq", kind=MANAGED, label="Groq",
        base_url="https://api.groq.com/openai/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env="GROQ_API_KEY",
        latency_ms=(10, 40),
        price_source="DeepInfRA rate for the same model",
    ),
    "cerebras": Endpoint(
        key="cerebras", kind=MANAGED, label="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.02", output_per_mtok_usd="0.04",
        api_key_env="CEREBRAS_API_KEY",
        latency_ms=(12, 45),
        price_source="DeepInfRA rate for the same model",
    ),
    "replicate": Endpoint(
        key="replicate", kind=MANAGED, label="Replicate",
        base_url="https://api.replicate.com/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="REPLICATE_API_TOKEN",
        latency_ms=(80, 200),
        price_source="DeepInfRA rate for the same model",
    ),
    "baseten": Endpoint(
        key="baseten", kind=MANAGED, label="Baseten",
        base_url="https://inference.baseten.co/v1",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        protocol="openai",
        input_per_mtok_usd="0.10", output_per_mtok_usd="0.32",
        api_key_env="BASETEN_API_KEY",
        latency_ms=(50, 120),
        price_source="DeepInfRA rate for the same model",
    ),
    "mistral": Endpoint(
        key="mistral", kind=MANAGED, label="Mistral",
        base_url="https://api.mistral.ai/v1",
        model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
        protocol="openai",
        input_per_mtok_usd="0.075", output_per_mtok_usd="0.20",
        api_key_env="MISTRAL_API_KEY",
        latency_ms=(40, 100),
        price_source="https://deepinfra.com/pricing (2026-10-22)",
    ),
    "nvidia_nim": Endpoint(
        key="nvidia_nim", kind=MANAGED, label="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/NVIDIA-Nemotron-3.5-Lightning",
        protocol="openai",
        input_per_mtok_usd="0.06", output_per_mtok_usd="0.16",
        api_key_env="NVIDIA_API_KEY",
        latency_ms=(35, 90),
        price_source="https://deepinfra.com/pricing (2026-10-22)",
    ),
    # --- 04. cloud gateways. OpenAI-compatible gateways in front of a cloud.
    "bedrock": Endpoint(
        key="bedrock", kind=GATEWAY, label="Amazon Bedrock",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
        model="claude-haiku-4-5",
        protocol="openai",
        input_per_mtok_usd="1.00", output_per_mtok_usd="5.00",
        api_key_env="AWS_BEARER_TOKEN_BEDROCK",
        latency_ms=(500, 1200),
        price_source="bundled catalog rate for the model",
        note="The gateway speaks OpenAI; the model behind it is not yours to pick per request.",
    ),
    "azure_openai": Endpoint(
        key="azure_openai", kind=GATEWAY, label="Azure OpenAI",
        base_url="https://example-resource.openai.azure.com/openai/v1",
        model="gpt-5.6-luna",
        protocol="openai",
        input_per_mtok_usd="0.20", output_per_mtok_usd="1.20",
        api_key_env="AZURE_OPENAI_API_KEY",
        latency_ms=(400, 900),
        price_source="bundled catalog rate for the model",
    ),
    "vertex_ai": Endpoint(
        key="vertex_ai", kind=GATEWAY, label="Google Vertex AI",
        base_url="https://aiplatform.googleapis.com/v1/projects/example/locations/us-central1/endpoints/openapi",
        model="gemini-2.5-pro",
        protocol="openai",
        input_per_mtok_usd="1.25", output_per_mtok_usd="10.00",
        api_key_env="GOOGLE_API_KEY",
        latency_ms=(450, 1000),
        price_source="public Vertex AI rate card",
    ),
}


@dataclass(frozen=True)
class Tenant:
    """One caller in a scenario: a customer, an agent, or a team.

    ``rpm`` is the *demo* rate. The real-world rate is in the scenario's
    ``real_rate`` string, and the demo prints both, because a rate nobody
    could recognise is a rate that proves nothing.
    """

    name: str
    label: str
    limit_tokens: int
    limit_usd: str | None
    rpm: float
    tokens_in: int
    tokens_out: int
    behaviour: str = "normal"
    #: The token counts this tenant sends once it has started going wrong.
    #: Equal to the healthy shape unless the failure *is* a change of shape.
    tokens_in_loop: int = 0
    tokens_out_loop: int = 0
    #: Whether this tenant has a cap of its own. A capped tenant is
    #: reserved against its own bucket, which is how one noisy neighbour is
    #: cut off without a platform-wide cut. An uncapped tenant spends against
    #: the shared pool, which is where the rest of the traffic goes.
    capped: bool = True
    #: The name of the tenant this one is the fixed version of. Two tenants
    #: with the same budget, one over-retrieving and one not, and the report
    #: says how many more answers the fixed one bought.
    fixed_version_of: str = ""
    team: str = "core"
    feature: str = ""
    #: A tenant in a loop sends this many times the normal rate.
    loop_multiplier: float = 1.0
    #: How long the tenant behaves normally before it goes wrong.
    healthy_for_s: float = 0.0


@dataclass(frozen=True)
class Scenario:
    """A real production failure, reproduced at its real parameters."""

    key: str
    title: str
    kind: str
    incident: str
    source_url: str
    endpoint: Endpoint
    tenants: list[Tenant]
    duration_s: float
    real_rate: str
    real_spend: str
    scale: str
    headline: str
    #: The guards this scenario is meant to show, in the order they trip.
    shows: list[str] = field(default_factory=list)
    #: Extra configuration the driver applies to the Backstop config.
    budget_tokens: int = 2_000_000
    budget_usd: str | None = None
    initial_concurrency: int = 8
    max_concurrency: int = 32
    circuit_failure_threshold: float = 0.5
    circuit_window_seconds: float = 6.0
    circuit_cooldown_seconds: float = 4.0
    retry_max_attempts: int = 1


SCENARIOS: list[Scenario] = [
    Scenario(
        key="noisy-neighbour",
        title="The $10,000 Overnight",
        kind=MANAGED,
        incident=(
            "A multi-tenant AI SaaS. One customer's agent falls into a loop and "
            "burns $10,000 overnight. The other 199 customers are fine, and "
            "they are the ones who churn."
        ),
        source_url="https://docs.portkey.ai/docs/guides/use-cases/multi-tenant-ai-feature",
        endpoint=ENDPOINTS["deepinfra"],
        duration_s=40.0,
        real_rate="Enterprise 1,000 rpm · Professional 100 rpm · Starter 10 rpm",
        real_spend="$20,500/month baseline; one tenant can reach $10,000 overnight",
        scale="the rate and the cap are scaled together — the ratio is the point",
        headline=(
            "One tenant's loop is cut off at its own cap. The other two tenants "
            "never notice."
        ),
        shows=[
            "a per-tenant budget that stops one tenant without touching the others",
            "the Tenants panel, per-tenant, live",
        ],
        budget_tokens=20_000_000,
        budget_usd="50.00",
        initial_concurrency=8,
        max_concurrency=32,
        tenants=[
            Tenant(
                name="acme", label="Acme (Enterprise)",
                limit_tokens=200_000, limit_usd="0.02",
                rpm=8.0, tokens_in=2_500, tokens_out=300,
                behaviour="loop", loop_multiplier=22.0, healthy_for_s=6.0,
                team="acme-corp",
            ),
            Tenant(
                name="globex", label="Globex (Professional)",
                limit_tokens=200_000, limit_usd="5.00",
                rpm=30.0, tokens_in=2_500, tokens_out=300,
                capped=False, team="globex-inc",
            ),
            Tenant(
                name="initech", label="Initech (Starter)",
                limit_tokens=200_000, limit_usd="25.00",
                rpm=12.0, tokens_in=2_500, tokens_out=300,
                capped=False, team="initech",
            ),
        ],
    ),
    Scenario(
        key="agent-loop",
        title="The 11-Day Ping-Pong",
        kind=PROVIDER_API,
        incident=(
            "Four agents in a research pipeline. Two of them — analysis and "
            "verification — lock into a recursive loop and keep it for eleven "
            "days. Every health check passes the whole time. The bill is "
            "$47,000."
        ),
        source_url=(
            "https://techstartups.com/2025/11/14/ai-agents-horror-stories-how-a-"
            "47000-failure-exposed-the-hype-and-hidden-risks-of-multi-agent-systems/"
        ),
        endpoint=ENDPOINTS["anthropic"],
        duration_s=40.0,
        real_rate="8 → 90 rpm over four weeks, 30 concurrent, 12,000 in / 900 out",
        real_spend="$127 → $891 → $6,240 → $18,400 per week, $47,000 over 11 days",
        scale="the rate and the cap are scaled together — the ratio is the point",
        headline=(
            "One agent's session hits its cap and stops. The other three keep "
            "working, and the ledger says which one it was."
        ),
        shows=[
            "a per-session cap that stops one agent, not the pipeline",
            "spend attributed per agent, so the expensive one is nameable",
        ],
        budget_tokens=20_000_000,
        budget_usd="50.00",
        initial_concurrency=8,
        max_concurrency=32,
        tenants=[
            Tenant(
                name="research", label="Research agent",
                limit_tokens=2_000_000, limit_usd="8.00",
                rpm=8.0, tokens_in=12_000, tokens_out=900,
                capped=False, team="research-pipeline",
            ),
            Tenant(
                name="analysis", label="Analysis agent",
                limit_tokens=2_000_000, limit_usd="0.60",
                rpm=2.0, tokens_in=12_000, tokens_out=900,
                behaviour="loop", loop_multiplier=33.0, healthy_for_s=8.0,
                team="research-pipeline",
            ),
            Tenant(
                name="verification", label="Verification agent",
                limit_tokens=2_000_000, limit_usd="0.90",
                rpm=2.0, tokens_in=12_000, tokens_out=900,
                behaviour="loop", loop_multiplier=22.0, healthy_for_s=8.0,
                team="research-pipeline",
            ),
            Tenant(
                name="summary", label="Summary agent",
                limit_tokens=2_000_000, limit_usd="8.00",
                rpm=4.0, tokens_in=12_000, tokens_out=900,
                capped=False, team="research-pipeline",
            ),
        ],
    ),
    Scenario(
        key="retry-storm",
        title="The Thundering Herd",
        kind=SELF_HOSTED,
        incident=(
            "Fifty agent workflows hit a self-hosted vLLM server that starts "
            "returning 429s. Every workflow retries with the full context, "
            "retries spawn retries, and a queue of users pressing refresh "
            "multiplies the load again."
        ),
        source_url="https://tianpan.co/blog/2026/04/10/retry-storm-problem-agentic-systems",
        endpoint=ENDPOINTS["vllm"],
        duration_s=45.0,
        real_rate="200 req/min baseline, 50 concurrent, rising to 200+ in the storm",
        real_spend="Retries re-send 8,000 tokens a piece — the token cost multiplies with the request count",
        scale="the rate is scaled down; the storm is what is being shown",
        headline=(
            "The breaker opens on the endpoint that is failing, the concurrency "
            "cap holds the line, and the queue does not grow without bound."
        ),
        shows=[
            "a circuit breaker that opens on a failing endpoint and half-opens to probe",
            "AIMD concurrency backing off instead of piling on",
        ],
        budget_tokens=20_000_000,
        budget_usd="50.00",
        initial_concurrency=6,
        max_concurrency=24,
        circuit_failure_threshold=0.35,
        circuit_window_seconds=5.0,
        circuit_cooldown_seconds=3.0,
        retry_max_attempts=3,
        tenants=[
            Tenant(
                name="workflows", label="50 agent workflows",
                limit_tokens=8_000_000, limit_usd="5.00",
                rpm=30.0, tokens_in=8_000, tokens_out=600, capped=False,
                behaviour="storm", loop_multiplier=8.0, healthy_for_s=10.0,
                team="agent-fleet",
            ),
        ],
    ),
    Scenario(
        key="rag-peak",
        title="The $47,000 RAG Bot",
        kind=MANAGED,
        incident=(
            "A customer-facing RAG bot on DeepInfra. It retrieves eight "
            "500-token chunks for every question whether the question needs "
            "them or not. At peak it is the second-largest line on the "
            "invoice, and most of the money buys tokens nobody reads."
        ),
        source_url="https://compresr.ai/blog/rag-over-retrieval-token-costs-guide",
        endpoint=ENDPOINTS["deepinfra"],
        duration_s=45.0,
        real_rate="1,400 rpm average, 3,600 rpm peak, 2M requests a day",
        real_spend="$47,000/month over-retrieving, $17,000/month optimised",
        scale="the rate is scaled down; the shape of the traffic is the point",
        headline=(
            "The same budget buys nearly three times as many answers once the "
            "bot stops retrieving chunks it does not need."
        ),
        shows=[
            "the per-call cost, in the ledger, where the over-retrieval is visible",
            "two tenants on one budget: one over-retrieving, one not",
        ],
        budget_tokens=20_000_000,
        budget_usd="50.00",
        initial_concurrency=16,
        max_concurrency=64,
        tenants=[
            Tenant(
                name="support-over", label="Support bot, over-retrieving",
                limit_tokens=200_000, limit_usd="0.01",
                rpm=40.0, tokens_in=6_000, tokens_out=600,
                team="customer-support",
            ),
            Tenant(
                name="support-fixed", label="Support bot, retrieval fixed",
                limit_tokens=200_000, limit_usd="0.01",
                rpm=40.0, tokens_in=1_500, tokens_out=400,
                fixed_version_of="support-over",
                team="customer-support",
            ),
            Tenant(
                name="search", label="Site search traffic",
                limit_tokens=200_000, limit_usd="0.10",
                rpm=20.0, tokens_in=1_200, tokens_out=200,
                capped=False, team="customer-support",
            ),
        ],
    ),
    Scenario(
        key="cloud-gateway",
        title="The $50,000 Unattributed Bill",
        kind=GATEWAY,
        incident=(
            "A large organisation runs thirty-five teams against a cloud "
            "gateway. The bill is $50,000 a month and nobody can say which "
            "team's MCP tools drove it, because the gateway does not attribute "
            "and the provider only bills the account."
        ),
        source_url="https://news.ycombinator.com/item?id=44848323",
        endpoint=ENDPOINTS["bedrock"],
        duration_s=45.0,
        real_rate="35 teams, per-team model mix of 80% small / 15% mid / 5% large",
        real_spend="$50,000 a month, unattributed",
        scale="the rate and the cap are scaled together — the ratio is the point",
        headline=(
            "One team is named in the ledger by the end of the run, and the "
            "other thirty-four are untouched."
        ),
        shows=[
            "spend attributed per team, which is the answer the $50,000 question needed",
            "a per-team budget that stops one team without a platform-wide cut",
        ],
        budget_tokens=20_000_000,
        budget_usd="50.00",
        initial_concurrency=8,
        max_concurrency=32,
        tenants=[
            Tenant(
                name="mcp-tools", label="The team with the MCP tools",
                limit_tokens=700_000, limit_usd="0.25",
                rpm=4.0, tokens_in=8_000, tokens_out=1_200,
                behaviour="loop", loop_multiplier=20.0, healthy_for_s=9.0,
                team="platform-tools",
            ),
            Tenant(
                name="support", label="Support tooling",
                limit_tokens=700_000, limit_usd="5.00",
                rpm=20.0, tokens_in=8_000, tokens_out=1_200,
                capped=False, team="customer-support",
            ),
            Tenant(
                name="data", label="Data platform",
                limit_tokens=700_000, limit_usd="5.00",
                rpm=12.0, tokens_in=8_000, tokens_out=1_200,
                capped=False, team="data-platform",
            ),
            Tenant(
                name="growth", label="Growth engineering",
                limit_tokens=700_000, limit_usd="5.00",
                rpm=8.0, tokens_in=8_000, tokens_out=1_200,
                capped=False, team="growth",
            ),
        ],
    ),
]

SCENARIOS_BY_KEY = {s.key: s for s in SCENARIOS}
