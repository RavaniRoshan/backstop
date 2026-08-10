import { createHash, createHmac } from "node:crypto";
import type { AuditSink } from "./types.js";

export interface AuditRecord {
  ts: number;
  decision: string;
  reason: string;
  _chain: string;
  [key: string]: unknown;
}

function chainHash(prev: Buffer, payload: Buffer, key: Buffer): string {
  const mac = createHmac("sha256", key).update(Buffer.concat([prev, payload])).digest();
  return createHash("sha256").update(Buffer.concat([prev, mac])).digest("hex");
}

/**
 * Tamper-evident audit log. Mirrors the Python AuditLog.
 */
export class AuditLog {
  private key: Buffer;
  private prev = Buffer.alloc(0);
  private file: NodeJS.WritableStream | null = null;
  private callable: ((line: string) => void) | null = null;
  private lines: string[] = [];

  constructor(sink: AuditSink | null, hmacKey?: string) {
    this.key = Buffer.from(hmacKey ?? "", "utf-8");
    if (typeof sink === "string") {
      const fs = require("node:fs") as typeof import("node:fs");
      this.file = fs.createWriteStream(sink, { flags: "a" });
    } else if (typeof sink === "function") {
      this.callable = sink;
    }
  }

  record(decision: string, reason: string, fields: Record<string, unknown> = {}): AuditRecord {
    const rec = { ts: Date.now(), decision, reason, ...fields };
    const payload = Buffer.from(JSON.stringify(rec), "utf-8");
    const chain = chainHash(this.prev, payload, this.key);
    const full = { ...rec, _chain: chain };
    this.prev = Buffer.from(chain, "hex");
    const line = JSON.stringify(full);
    this.lines.push(line);
    if (this.file) this.file.write(line + "\n");
    if (this.callable) this.callable(line);
    return full;
  }

  verify(lines?: string[]): boolean {
    let prev = Buffer.alloc(0);
    const src = lines ?? [...this.lines];
    for (const line of src) {
      const rec = JSON.parse(line);
      const { _chain, ...rest } = rec;
      const payload = Buffer.from(JSON.stringify(rest), "utf-8");
      const expected = chainHash(prev, payload, this.key);
      if (expected !== _chain) return false;
      prev = Buffer.from(_chain, "hex");
    }
    return true;
  }

  close(): void {
    if (this.file) {
      this.file.end();
      this.file = null;
    }
  }
}
