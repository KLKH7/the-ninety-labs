// "Connect your phone": pairs this viewer with the phone companion (web/phone) through the API's
// rooms (ninety/api/companion.py). The laptop asks for a 6-character code, shows it with a QR code
// of the phone's address, and sends its clock to the room: about once a second while it plays, and
// at once on every play, pause and seek, so the phones stay in step with the video. The clock is
// match time; the QR code also names the bundle, so the phone reads the same cuts (segments) and
// tracked positions and runs its clock across a cut the way the video does.

import qrcode from "qrcode-generator";

const EVERY_MS = 1000; // design: the phone runs the clock on between messages; once a second corrects drift
const MIN_GAP_MS = 200; // the API's relay allows 600 messages a minute; a dragged scrubber stays under it
// design: past the phone's 0.2 s tolerance (web/phone/src/clock.ts) with room for a frame's jitter,
// so a seek is sent at once and ordinary playback is not.
const JUMP_S = 0.3;
const RETRY_MS = 2000; // design: a restarting server is back within seconds; a phone retries as often
const KEPT = "ninety.pairCode"; // this tab's code, re-claimed after a reload as after a restart

type QRCode = ReturnType<typeof qrcode>;

export interface Playback {
  time(): number; // match time, in seconds
  playing(): boolean;
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export class PhonePanel {
  private ws: WebSocket | null = null;
  private sentAt = 0;
  private sentT = 0;
  private sentPlaying = false;
  private code = "";
  /** Called with each new code and the phone's address for it (src/dock.ts embeds that address). */
  private listener: ((code: string, url: string, qr: QRCode) => void) | null = null;
  private last: [string, string, QRCode] | null = null;
  set onCode(f: (code: string, url: string, qr: QRCode) => void) {
    this.listener = f;
    if (this.last) f(...this.last); // paired before anyone listened
  }

  /** Whether a pairing code is up, so the big screen's card has something to show. */
  get paired(): boolean {
    return this.code !== "";
  }

  /** `bundle` is the bundle's path on this origin; `auto` pairs at once (the big screen shows its
   * QR code without a click). */
  constructor(
    private readonly clip: string,
    private readonly playback: Playback,
    private readonly bundle: string,
    auto = false,
  ) {
    $("phone-pair").addEventListener("click", () => void this.pair());
    this.auto = auto;
    if (auto) void this.pair(kept());
  }
  private readonly auto: boolean;

  private say(state: string, error = "") {
    $("phone-state").textContent = state;
    $("phone-error").textContent = error;
  }

  /** A new code, or `again` back: the code this screen showed, after the server restarted (its
   * rooms are in memory) or this tab reloaded, so the phones on it rejoin without a rescan. */
  private async pair(again: string | null = null): Promise<void> {
    const button = $<HTMLButtonElement>("phone-pair");
    button.disabled = true;
    this.ws?.close(1000);
    this.ws = null;
    let response: Response;
    try {
      response = await fetch(new URL("api/pair", location.href), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(again ? { clip: this.clip, code: again } : { clip: this.clip }),
      });
    } catch {
      button.disabled = false;
      this.say("", "Could not reach the server.");
      // The big screen keeps trying, for the same code: the server may be restarting.
      if (this.auto) setTimeout(() => void this.pair(again ?? (this.code || null)), RETRY_MS);
      return;
    }
    button.disabled = false;
    // Taken meanwhile, or not a code this server takes: a new code.
    if (again && (response.status === 409 || response.status === 422)) return this.pair();
    // A restarting host's front door (Azure's ingress answers 502/503 meanwhile, not our JSON):
    // try again. Our own 503s (no rooms left, a clip it may not serve) are answers, not outages.
    if (this.auto && response.status >= 500 && !response.headers.get("content-type")?.includes("json")) {
      this.say("Reconnecting…");
      setTimeout(() => void this.pair(again ?? (this.code || null)), RETRY_MS);
      return;
    }
    if (response.status === 404 || response.status === 405) {
      this.say("", "The phone companion is off on this server.");
      return;
    }
    const body = (await response.json().catch(() => ({}))) as { code?: string; error?: string };
    if (response.status === 422) {
      this.say("", "This clip has no phone companion yet.");
      return;
    }
    if (!response.ok || !body.code) {
      this.say("", body.error ?? `The server answered ${response.status}.`);
      return;
    }
    this.code = body.code;
    keep(body.code);
    this.show(body.code);
    this.open();
  }

  private show(code: string) {
    const url = new URL(`phone/?${new URLSearchParams({ code, clip: this.clip, bundle: this.bundle })}`, location.href).toString();
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    // The SVG is built by the library from our own URL; nothing a viewer typed goes into it.
    $("phone-qr").innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
    $("phone-code").textContent = code;
    // The big screen's card: a short address and the code in two groups of three, as TV apps write it.
    $("pair-qr").innerHTML = qr.createSvgTag({ cellSize: 3, margin: 1, scalable: true });
    $("pair-url").textContent = `${location.host}/phone`;
    $("pair-code").textContent = `${code.slice(0, 3)} ${code.slice(3)}`;
    const link = $<HTMLAnchorElement>("phone-link");
    link.href = url;
    link.textContent = new URL("phone/", location.href).toString();
    $("phone-pairing").hidden = false;
    $<HTMLButtonElement>("phone-pair").textContent = "New code";
    this.last = [code, url, qr];
    this.listener?.(...this.last);
  }

  private open() {
    const u = new URL(`api/pair/${this.code}`, location.href);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.searchParams.set("role", "laptop");
    const ws = new WebSocket(u);
    this.ws = ws;
    ws.addEventListener("open", () => {
      this.say("Phones that join now follow this video.");
      this.send();
    });
    ws.addEventListener("close", (e) => {
      if (this.ws !== ws) return; // replaced by a new code
      this.ws = null;
      // Unknown: the server restarted and lost its rooms, so the big screen claims the same code
      // back. Expired: a new one.
      if (e.code === 4404 && this.auto) {
        this.say("Reconnecting…");
        setTimeout(() => this.ws === null && void this.pair(this.code), 0);
      } else if (e.code === 4410 && this.auto) void this.pair();
      else if (e.code === 4404 || e.code === 4410) this.say("", "This code has expired. Get a new one.");
      else if (e.code === 4409) this.say("", "Another window is already sending this code's clock.");
      else if (e.code !== 1000) {
        this.say("Reconnecting…");
        setTimeout(() => this.ws === null && this.code && this.open(), RETRY_MS);
      }
    });
  }

  private send() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const t = Math.max(0, this.playback.time());
    const playing = this.playback.playing();
    this.ws.send(JSON.stringify({ type: "clock", t: Math.round(t * 100) / 100, playing }));
    this.sentAt = performance.now();
    this.sentT = t;
    this.sentPlaying = playing;
  }

  /** Called every animation frame: sends the clock when it is due or when the viewer seeked. */
  tick() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const now = performance.now();
    const since = now - this.sentAt;
    if (since < MIN_GAP_MS) return;
    const expected = this.sentT + (this.sentPlaying ? since / 1000 : 0);
    const jumped = Math.abs(this.playback.time() - expected) > JUMP_S;
    if (since >= EVERY_MS || jumped || this.playback.playing() !== this.sentPlaying) this.send();
  }
}

/** The tab's pairing code, kept for a reload; storage may be missing or throw. */
function kept(): string | null {
  try {
    return sessionStorage.getItem(KEPT);
  } catch {
    return null;
  }
}
function keep(code: string) {
  try {
    sessionStorage.setItem(KEPT, code);
  } catch {
    /* not kept */
  }
}
