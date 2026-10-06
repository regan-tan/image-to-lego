import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the project title and successful backend status", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderApp();

    expect(screen.getByRole("heading", { name: "Image to LEGO" })).toBeInTheDocument();
    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
  });

  it("renders an unavailable state when the health request fails", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("network unavailable"));

    renderApp();

    expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
  });
});
