import type { Priority } from "./types.js";

interface Ticket {
  priority: Priority;
  sequence: number;
  enqueuedAt: number;
}

/**
 * Additive-increase/multiplicative-decrease concurrency controller.
 * Mirrors the Python AIMDController.
 */
export class AIMDController {
  private limit: number;
  private lastAdjustment: number;
  private readonly minLimit: number;
  private readonly maxLimit: number;
  private readonly increase: number;
  private readonly decreaseFactor: number;
  private readonly intervalMs: number;

  constructor(opts: {
    initial: number;
    min: number;
    max: number;
    increase?: number;
    decreaseFactor: number;
    intervalMs: number;
  }) {
    this.limit = opts.initial;
    this.minLimit = opts.min;
    this.maxLimit = opts.max;
    this.increase = opts.increase ?? 1;
    this.decreaseFactor = opts.decreaseFactor;
    this.intervalMs = opts.intervalMs;
    this.lastAdjustment = -opts.intervalMs;
  }

  get currentLimit(): number {
    return this.limit;
  }

  recordSuccess(): boolean {
    const now = Date.now();
    if (now - this.lastAdjustment < this.intervalMs) return false;
    if (this.limit >= this.maxLimit) return false;
    this.limit = Math.min(this.maxLimit, this.limit + this.increase);
    this.lastAdjustment = now;
    return true;
  }

  recordPressure(): boolean {
    const now = Date.now();
    if (now - this.lastAdjustment < this.intervalMs) return false;
    const next = Math.max(this.minLimit, Math.floor(this.limit * this.decreaseFactor));
    if (next === this.limit) return false;
    this.limit = next;
    this.lastAdjustment = now;
    return true;
  }

  applyExternalDecrease(pressure = 1): boolean {
    const factor = Math.max(this.decreaseFactor, Math.min(1, pressure));
    const next = Math.min(this.maxLimit, Math.max(this.minLimit, Math.floor(this.limit * factor)));
    if (next === this.limit) return false;
    this.limit = next;
    this.lastAdjustment = Date.now();
    return true;
  }
}

/**
 * Priority admission gate with starvation prevention.
 * Mirrors the Python PriorityGate.
 */
export class PriorityGate {
  private active = 0;
  private seq = 0;
  private readonly queues: Record<Priority, Ticket[]> = {
    critical: [],
    high: [],
    default: [],
    low: [],
    bulk: [],
  };
  private readonly aimd: AIMDController;
  private readonly starvationMs: number;
  private readonly timeoutMs: number | null;
  /** The waiters to re-check when a slot frees. */
  private readonly waiters = new Set<() => void>();

  constructor(aimd: AIMDController, opts: { starvationMs: number; timeoutMs: number | null }) {
    this.aimd = aimd;
    this.starvationMs = opts.starvationMs;
    this.timeoutMs = opts.timeoutMs;
  }

  get depth(): number {
    return Object.values(this.queues).reduce((n, q) => n + q.length, 0);
  }

  acquire(priority: Priority): Promise<number> {
    return new Promise((resolve, reject) => {
      const ticket: Ticket = { priority, sequence: this.seq++, enqueuedAt: Date.now() };
      this.queues[priority].push(ticket);
      let done = false;

      let timer: ReturnType<typeof setTimeout> | null = null;

      const cleanup = () => {
        done = true;
        this.waiters.delete(tryAdmit);
        if (timer !== null) { clearTimeout(timer); timer = null; }
      };

      const tryAdmit = () => {
        if (done) return;
        if (this.canAdmit(ticket)) {
          const idx = this.queues[priority].indexOf(ticket);
          if (idx >= 0) this.queues[priority].splice(idx, 1);
          this.active++;
          cleanup();
          resolve(Date.now() - ticket.enqueuedAt);
        }
      };

      const giveUp = () => {
        if (done) return;
        const idx = this.queues[priority].indexOf(ticket);
        if (idx >= 0) this.queues[priority].splice(idx, 1);
        cleanup();
        reject(new Error("gate acquire timed out"));
      };

      // Register before the first check, so a release that lands between the
      // check and the registration cannot be missed.
      this.waiters.add(tryAdmit);
      tryAdmit();

      // The timeout is a timer of its own, not a check made when something
      // else happens. It used to be evaluated inside the admission check, so
      // it only fired when a slot was released — which meant a request that
      // was never woken up sat there past its deadline and past it, forever.
      if (this.timeoutMs != null) {
        timer = setTimeout(giveUp, this.timeoutMs);
      }
    });
  }

  release(): void {
    this.active = Math.max(0, this.active - 1);
    // A slot just freed. Wake the waiters, rather than making them wait for
    // a timer to notice.
    //
    // The waiters used to poll, and only when a timeout was configured: with
    // the default `queueTimeoutMs: null` a request that could not be
    // admitted immediately was never re-checked, so it waited for a slot that
    // freed later and was never told. The request hung forever, with no
    // error and no timeout — the same failure the Python package's gate had
    // until v0.8.0, in a port that had never been exercised under load.
    for (const waiter of [...this.waiters]) waiter();
  }

  private canAdmit(ticket: Ticket): boolean {
    if (this.active >= this.aimd.currentLimit) return false;
    return this.chooseTicket() === ticket;
  }

  private chooseTicket(): Ticket | null {
    // The order is the priority order: critical, high, default, low, bulk.
    //
    // `high` used to be missing from the second list, so a high-priority
    // ticket was enqueued and then never chosen: it could not be admitted,
    // and it waited for a slot that was never offered to it.
    if (this.queues.critical.length) return this.queues.critical[0];
    const now = Date.now();
    for (const q of [this.queues.high, this.queues.default, this.queues.low, this.queues.bulk]) {
      if (q.length && now - q[0].enqueuedAt >= this.starvationMs) return q[0];
    }
    for (const q of [this.queues.high, this.queues.default, this.queues.low, this.queues.bulk]) {
      if (q.length) return q[0];
    }
    return null;
  }
}
