import type { Session } from "@supabase/supabase-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IDLE_TIMEOUT_MS, idleSessionKey, isSessionIdle, watchIdleSession } from "./idleSession";

const session = {
  user: { id: "builder", last_sign_in_at: "2026-11-01T08:00:00Z" },
} as Session;

describe("idle session", () => {
  let stopWatching: (() => void) | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-01T08:00:00Z"));
    localStorage.clear();
  });

  afterEach(() => {
    stopWatching?.();
    stopWatching = undefined;
    localStorage.clear();
    vi.useRealTimers();
  });

  it("expires exactly once after ten idle minutes", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1);
    expect(expire).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    window.dispatchEvent(new Event("focus"));
    expect(expire).toHaveBeenCalledOnce();
  });

  it("extends the deadline on user activity", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    vi.advanceTimersByTime(5 * 60 * 1000);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "a" }));
    vi.advanceTimersByTime(IDLE_TIMEOUT_MS - 1);
    expect(expire).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(expire).toHaveBeenCalledOnce();
  });

  it("preserves elapsed time across reloads or token refreshes", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    vi.advanceTimersByTime(6 * 60 * 1000);
    stopWatching();
    stopWatching = watchIdleSession({ ...session, access_token: "refreshed" }, expire);
    vi.advanceTimersByTime(4 * 60 * 1000);
    expect(expire).toHaveBeenCalledOnce();
  });

  it("does not revive an expired session on the first event after sleep", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    vi.setSystemTime(Date.now() + IDLE_TIMEOUT_MS);
    window.dispatchEvent(new Event("pointerdown"));
    expect(expire).toHaveBeenCalledOnce();
    expect(isSessionIdle(session)).toBe(true);
  });

  it("uses activity from another tab without treating focus as activity", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    vi.advanceTimersByTime(5 * 60 * 1000);
    localStorage.setItem(idleSessionKey(session), String(Date.now()));
    window.dispatchEvent(new StorageEvent("storage", { key: idleSessionKey(session) }));
    vi.advanceTimersByTime(5 * 60 * 1000);
    window.dispatchEvent(new Event("focus"));
    expect(expire).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5 * 60 * 1000);
    expect(expire).toHaveBeenCalledOnce();
  });

  it("detects a saved expired session but gives a fresh sign-in a new clock", () => {
    localStorage.setItem(idleSessionKey(session), String(Date.now() - IDLE_TIMEOUT_MS));
    expect(isSessionIdle(session)).toBe(true);
    expect(isSessionIdle({
      ...session,
      user: { ...session.user, last_sign_in_at: "2026-11-01T09:00:00Z" },
    })).toBe(false);
  });

  it("removes timers and event listeners on cleanup", () => {
    const expire = vi.fn();
    stopWatching = watchIdleSession(session, expire);
    stopWatching();
    const saved = localStorage.getItem(idleSessionKey(session));
    vi.advanceTimersByTime(IDLE_TIMEOUT_MS);
    window.dispatchEvent(new Event("pointerdown"));
    expect(expire).not.toHaveBeenCalled();
    expect(localStorage.getItem(idleSessionKey(session))).toBe(saved);
  });
});
