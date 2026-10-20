// The laptop's clock on the phone. The laptop sends {t, playing} about once a second and on every
// play, pause and seek (web/viewer/src/companion.ts); between messages the phone runs the clock on
// from the last one. tests/test_phone.py holds the phone within TOLERANCE_S of the laptop.

import type { ClockMessage } from "./types";

/** One minimap frame at the feed's 5 fps: the phone cannot show the match any finer than this. */
export const TOLERANCE_S = 0.2;
/** The laptop sends at least once a second; after this long without a message the phone stops
 * running the clock on and says it lost the laptop, rather than drift ahead of a stalled video. */
export const STALE_S = 4;

export class LaptopClock {
  private t = 0;
  private playing = false;
  private at = 0; // performance.now() when the last message arrived
  heard = false;

  constructor(private readonly now: () => number = () => performance.now()) {}

  update(m: ClockMessage) {
    this.t = m.t;
    this.playing = m.playing;
    this.at = this.now();
    this.heard = true;
  }

  /** Seconds since the last message. */
  age(): number {
    return (this.now() - this.at) / 1000;
  }

  stale(): boolean {
    return this.heard && this.playing && this.age() > STALE_S;
  }

  isPlaying(): boolean {
    return this.playing && !this.stale();
  }

  /** Match time now, in seconds. */
  time(): number {
    return this.t + (this.playing ? Math.min(this.age(), STALE_S) : 0);
  }
}
