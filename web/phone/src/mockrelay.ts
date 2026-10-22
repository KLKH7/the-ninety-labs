// The mock relay: the laptop and the phone in one browser, talking over a BroadcastChannel instead
// of the API's WebSocket room. The laptop side runs in mock-laptop.html; the phone side in mock.ts.
// Same rules as the API's relay: only clock and focus messages, and a phone that joins late gets
// the latest of each first.

import type { RelayMessage } from "./types";

export const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // the API's (no 0/O, 1/I/L)
export const CODE_LENGTH = 6;
export const JOIN_TIMEOUT_MS = 2000;

interface Hello {
  hello: true;
}

export function channelName(code: string): string {
  return `ninety-mock-pair-${code}`;
}

export function newCode(random: () => number = Math.random): string {
  return Array.from({ length: CODE_LENGTH }, () => CODE_ALPHABET[Math.floor(random() * CODE_ALPHABET.length)]).join("");
}

/** The laptop's end: sends clock and focus, and repeats the latest to each phone that says hello. */
export class MockLaptop {
  private readonly channel: BroadcastChannel;
  private readonly latest = new Map<string, RelayMessage>();

  constructor(readonly code: string) {
    this.channel = new BroadcastChannel(channelName(code));
    this.channel.addEventListener("message", (e: MessageEvent<Hello | RelayMessage>) => {
      if ("hello" in e.data) for (const m of this.latest.values()) this.channel.postMessage(m);
    });
  }

  send(message: RelayMessage) {
    this.latest.set(message.type, message);
    this.channel.postMessage(message);
  }

  close() {
    this.channel.close();
  }
}

/** The phone's end: resolves once the laptop answered, rejects when no laptop has this code. */
export function joinMock(code: string, on: (m: RelayMessage) => void): Promise<{ close(): void }> {
  const channel = new BroadcastChannel(channelName(code));
  return new Promise((resolve, reject) => {
    let joined = false;
    const timer = setTimeout(() => {
      channel.close();
      reject("unknown-code");
    }, JOIN_TIMEOUT_MS);
    channel.addEventListener("message", (e: MessageEvent<Hello | RelayMessage>) => {
      if ("hello" in e.data) return;
      if (!joined) {
        joined = true;
        clearTimeout(timer);
        resolve({ close: () => channel.close() });
      }
      on(e.data);
    });
    channel.postMessage({ hello: true } satisfies Hello);
  });
}
