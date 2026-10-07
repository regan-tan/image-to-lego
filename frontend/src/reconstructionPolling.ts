const RECONSTRUCTION_POLL_INTERVAL_MS = 5_000;

export function reconstructionPollInterval(status: string | undefined): number | false {
  return status === "queued" || status === "running" ? RECONSTRUCTION_POLL_INTERVAL_MS : false;
}
