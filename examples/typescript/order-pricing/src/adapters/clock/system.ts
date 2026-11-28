import type { ClockPort } from "../../core/ports.js";

export class SystemClock implements ClockPort {
  now(): Date {
    return new Date();
  }
}
