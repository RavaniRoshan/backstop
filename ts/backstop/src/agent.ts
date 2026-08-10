/**
 * Agent-native guardrails. Mirrors the Python AgentGuard.
 */
export class AgentGuard {
  private maxCalls: number;
  private windowMs: number;
  private maxTokens: number | null;
  private calls = new Map<string, number[]>();
  private tokens = new Map<string, Array<[number, number]>>();

  constructor(opts: { maxCalls: number; windowMs: number; maxTokens: number | null }) {
    this.maxCalls = opts.maxCalls;
    this.windowMs = opts.windowMs;
    this.maxTokens = opts.maxTokens;
  }

  allow(agentId: string, tokens = 0): boolean {
    const now = Date.now();
    const cutoff = now - this.windowMs;

    const agentCalls = this.calls.get(agentId) ?? [];
    const trimmedCalls = agentCalls.filter((t) => t >= cutoff);
    if (trimmedCalls.length >= this.maxCalls) return false;
    trimmedCalls.push(now);
    this.calls.set(agentId, trimmedCalls);

    if (this.maxTokens != null && tokens > 0) {
      const agentTokens = this.tokens.get(agentId) ?? [];
      const trimmedTokens = agentTokens.filter(([t]) => t >= cutoff);
      const spent = trimmedTokens.reduce((n, [, tk]) => n + tk, 0);
      if (spent + tokens > this.maxTokens) return false;
      trimmedTokens.push([now, tokens]);
      this.tokens.set(agentId, trimmedTokens);
    }

    return true;
  }
}
