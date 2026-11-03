import type { Session } from "@supabase/supabase-js";

export const IDLE_TIMEOUT_MS = 10 * 60 * 1000;
const ACTIVITY_EVENTS = ["pointerdown", "pointermove", "keydown", "touchstart", "wheel"] as const;
const ACTIVITY_WRITE_INTERVAL_MS = 1000;

// A new sign-in gets its own clock; token refreshes retain the same clock.
export function idleSessionKey(session: Session): string {
  return `image-to-lego:last-activity:${session.user.id}:${session.user.last_sign_in_at ?? "existing"}`;
}

function lastActivityAt(key: string): number | null {
  const stored = localStorage.getItem(key);
  const timestamp = stored === null ? NaN : Number(stored);
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : null;
}

export function isSessionIdle(session: Session): boolean {
  const lastActivity = lastActivityAt(idleSessionKey(session));
  return lastActivity !== null && Date.now() - lastActivity >= IDLE_TIMEOUT_MS;
}

export function watchIdleSession(session: Session, onExpire: () => void): () => void {
  const key = idleSessionKey(session);
  let timer: ReturnType<typeof setTimeout>;
  let expired = false;
  if (lastActivityAt(key) === null) localStorage.setItem(key, String(Date.now()));

  function checkExpiry() {
    clearTimeout(timer);
    const remaining = IDLE_TIMEOUT_MS - (Date.now() - (lastActivityAt(key) ?? 0));
    if (remaining <= 0) {
      if (!expired) {
        expired = true;
        onExpire();
      }
      return;
    }
    timer = setTimeout(checkExpiry, remaining);
  }

  function recordActivity() {
    // An event after sleep or a suspended tab must not revive an expired session.
    checkExpiry();
    if (expired || document.visibilityState === "hidden") return;
    if (Date.now() - (lastActivityAt(key) ?? 0) >= ACTIVITY_WRITE_INTERVAL_MS) {
      localStorage.setItem(key, String(Date.now()));
      checkExpiry();
    }
  }

  function onStorage(event: StorageEvent) {
    if (event.key === key || event.key === null) checkExpiry();
  }

  for (const event of ACTIVITY_EVENTS) window.addEventListener(event, recordActivity, { passive: true });
  window.addEventListener("storage", onStorage);
  window.addEventListener("focus", checkExpiry);
  document.addEventListener("visibilitychange", checkExpiry);
  checkExpiry();

  return () => {
    clearTimeout(timer);
    for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, recordActivity);
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("focus", checkExpiry);
    document.removeEventListener("visibilitychange", checkExpiry);
  };
}
