/**
 * Cloud-quota-aware auto-tuning. Mirrors the Python QuotaMonitor.
 */
export class QuotaMonitor {
  private threshold: number;
  last: { requestPressure: number; tokenPressure: number; pressure: number } | null = null;

  constructor(threshold = 0.85) {
    this.threshold = threshold;
  }

  ingest(headers: Record<string, string>): void {
    const h: Record<string, string> = {};
    for (const [k, v] of Object.entries(headers)) h[k.toLowerCase()] = v;

    const reqLimit = Number(h["x-ratelimit-limit-requests"] ?? h["anthropic-ratelimit-requests-limit"]);
    const reqRem = Number(h["x-ratelimit-remaining-requests"] ?? h["anthropic-ratelimit-requests-remaining"]);
    const tokLimit = Number(h["x-ratelimit-limit-tokens"] ?? h["anthropic-ratelimit-tokens-limit"]);
    const tokRem = Number(h["x-ratelimit-remaining-tokens"] ?? h["anthropic-ratelimit-tokens-remaining"]);

    const requestPressure = reqLimit && reqRem != null ? 1 - reqRem / reqLimit : 0;
    const tokenPressure = tokLimit && tokRem != null ? 1 - tokRem / tokLimit : 0;
    this.last = { requestPressure, tokenPressure, pressure: Math.max(requestPressure, tokenPressure) };
  }

  adjust(aimd: { applyExternalDecrease(p?: number): boolean }): boolean {
    if (!this.last) return false;
    if (this.last.pressure >= this.threshold) {
      return aimd.applyExternalDecrease(this.last.pressure);
    }
    return false;
  }
}
