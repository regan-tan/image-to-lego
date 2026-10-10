import type { Conversion } from "./schemas/conversions";

export const CONVERSION_POLL_INTERVAL_MS = 3_000;

export function conversionPollInterval(status: Conversion["status"] | undefined): number | false {
  return status === "queued" || status === "running" ? CONVERSION_POLL_INTERVAL_MS : false;
}
