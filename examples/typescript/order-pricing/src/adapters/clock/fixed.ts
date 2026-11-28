import type { ClockPort } from "../../core/ports.js";

export class FixedClock implements ClockPort {
  constructor(private readonly value: Date) {}

  now(): Date {
    return this.value;
  }
}
