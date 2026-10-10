import { describe, expect, it } from "vitest";

import { legoColorHex, legoColorLabel } from "./legoColors";

describe("LEGO color registry", () => {
  it("maps canonical persisted colors to display colors", () => {
    expect(legoColorHex("reddish_brown")).toBe("#582A12");
    expect(legoColorHex("dark_green")).toBe("#184632");
  });

  it("falls back safely and keeps a readable color label", () => {
    expect(legoColorHex("future_color")).toBe("#A0A5A9");
    expect(legoColorLabel("reddish_brown")).toBe("Reddish Brown");
  });
});
