import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CreditBadge } from "./CreditBadge";

const mocks = vi.hoisted(() => ({ useCredits: vi.fn() }));
vi.mock("../hooks/useCredits", () => ({ useCredits: mocks.useCredits }));

afterEach(() => {
  cleanup();
  mocks.useCredits.mockReset();
});

describe("CreditBadge", () => {
  it("links the actual balance to the profile with an accessible label", () => {
    mocks.useCredits.mockReturnValue({ isPending: false, isError: false, data: { balance: 8 } });
    render(<MemoryRouter><CreditBadge accessToken="token" userId="user" /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "8 credits remaining" })).toHaveAttribute("href", "/profile");
  });

  it("does not show zero while the balance is loading or unavailable", () => {
    mocks.useCredits.mockReturnValue({ isPending: true, isError: false });
    const { rerender } = render(<MemoryRouter><CreditBadge accessToken="token" userId="user" /></MemoryRouter>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading credits");
    mocks.useCredits.mockReturnValue({ isPending: false, isError: true });
    rerender(<MemoryRouter><CreditBadge accessToken="token" userId="user" /></MemoryRouter>);
    expect(screen.getByRole("link", { name: /credits unavailable/i })).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });
});
