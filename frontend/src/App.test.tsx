import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Session } from "@supabase/supabase-js";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const authMock = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signInWithOAuth: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  signUp: vi.fn(),
}));

vi.mock("./lib/supabase", () => ({
  isSupabaseConfigured: true,
  supabase: { auth: authMock },
}));

const session: Session = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  expires_in: 3600,
  expires_at: 1_900_000_000,
  token_type: "bearer",
  user: {
    id: "user-123",
    aud: "authenticated",
    role: "authenticated",
    email: "builder@example.com",
    app_metadata: {},
    user_metadata: {},
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  },
};

function renderApp(initialRoute: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

function mockSignedOutSession() {
  authMock.getSession.mockResolvedValue({ data: { session: null } });
  authMock.onAuthStateChange.mockReturnValue({
    data: { subscription: { unsubscribe: vi.fn() } },
  });
}

function mockProfileResponse() {
  vi.mocked(fetch).mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "user-123",
        email: "builder@example.com",
        displayName: null,
        avatarUrl: null,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    mockSignedOutSession();
    authMock.signUp.mockResolvedValue({ data: { session: null }, error: null });
    authMock.signInWithPassword.mockResolvedValue({ data: { session: null }, error: null });
    authMock.signInWithOAuth.mockResolvedValue({ error: null });
    authMock.signOut.mockResolvedValue({ error: null });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("redirects unauthenticated visitors from the home page to login", async () => {
    renderApp("/");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the login page", async () => {
    renderApp("/login");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/signup");
  });

  it("renders the signup page", async () => {
    renderApp("/signup");

    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("starts email sign-up and shows email confirmation", async () => {
    renderApp("/signup");

    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign up" }));

    expect(authMock.signUp).toHaveBeenCalledWith({ email: "new@example.com", password: "safe-password" });
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
  });

  it("returns from signup confirmation to the login route", async () => {
    renderApp("/signup");

    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign up" }));
    fireEvent.click(await screen.findByRole("button", { name: "Back to sign in" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("navigates home after successful email and password login", async () => {
    authMock.signInWithPassword.mockResolvedValue({ data: { session }, error: null });
    mockProfileResponse();
    renderApp("/login");

    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "builder@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "safe-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Your profile" })).toBeInTheDocument();
    expect(authMock.signInWithPassword).toHaveBeenCalledWith({
      email: "builder@example.com",
      password: "safe-password",
    });
  });

  it("shows a safe error for invalid credentials", async () => {
    authMock.signInWithPassword.mockResolvedValue({
      data: { session: null },
      error: new Error("Invalid login credentials"),
    });
    renderApp("/login");

    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "builder@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not sign you in. Check your email and password and try again.",
    );
  });

  it("starts Google and GitHub OAuth with the application root redirect", async () => {
    const applicationRoot = new URL("/", window.location.origin).toString();
    renderApp("/login");

    fireEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));

    expect(authMock.signInWithOAuth).toHaveBeenNthCalledWith(1, {
      provider: "google",
      options: { redirectTo: applicationRoot },
    });
    expect(authMock.signInWithOAuth).toHaveBeenNthCalledWith(2, {
      provider: "github",
      options: { redirectTo: applicationRoot },
    });
  });

  it("redirects an authenticated user from login to home", async () => {
    authMock.getSession.mockResolvedValue({ data: { session } });
    mockProfileResponse();
    renderApp("/login");

    expect(await screen.findByRole("heading", { name: "Your profile" })).toBeInTheDocument();
  });

  it("redirects an authenticated user from signup to home", async () => {
    authMock.getSession.mockResolvedValue({ data: { session } });
    mockProfileResponse();
    renderApp("/signup");

    expect(await screen.findByRole("heading", { name: "Your profile" })).toBeInTheDocument();
  });

  it("sends the session access token to the profile endpoint", async () => {
    authMock.getSession.mockResolvedValue({ data: { session } });
    mockProfileResponse();
    renderApp("/");

    expect(await screen.findByText("builder@example.com")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/profile",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer test-access-token" }),
      }),
    );
  });

  it("signs out and returns to login", async () => {
    authMock.getSession.mockResolvedValue({ data: { session } });
    mockProfileResponse();
    renderApp("/");

    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(authMock.signOut).toHaveBeenCalledOnce();
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});
