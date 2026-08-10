/**
 * Cost forecasting + anomaly detection. Mirrors the Python forecast module.
 */
export function projectRemainingSeconds(usedTokens: number, windowSeconds: number, totalTokens: number): number {
  if (windowSeconds <= 0 || usedTokens <= 0) return Infinity;
  const rate = usedTokens / windowSeconds;
  const remaining = Math.max(0, totalTokens - usedTokens);
  return remaining / rate;
}

export function willExhaust(usedTokens: number, windowSeconds: number, totalTokens: number, horizonSeconds: number): boolean {
  return projectRemainingSeconds(usedTokens, windowSeconds, totalTokens) <= horizonSeconds;
}

export function detectSpendAnomaly(baselineRate: number, currentRate: number, sensitivity = 2): boolean {
  if (baselineRate <= 0) return currentRate > 0;
  return currentRate >= sensitivity * baselineRate;
}
