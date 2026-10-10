import { describe, expect, it } from "vitest";

import { createLegoPartsList, serializePartsListCsv } from "./legoPartsList";
import type { LegoModel } from "./schemas/legoModels";

function model(placements: LegoModel["placements"], partCount = placements.length): LegoModel {
  return { partCount, dimensions: { widthStuds: 4, depthStuds: 4, heightBricks: 2, widthMm: 32, depthMm: 32, heightMm: 19.2 }, metadata: { algorithmVersion: "test", sourceSha256: "a", targetParts: 10, occupiedCellCount: 1, gridSize: { widthStuds: 4, depthStuds: 4, heightBricks: 2 }, candidateCount: 1, occupancyMode: "test" }, placements };
}

function placement(overrides: Partial<LegoModel["placements"][number]> = {}): LegoModel["placements"][number] {
  return { brickType: "brick_2x4", dimensions: { lengthStuds: 2, widthStuds: 4, heightBricks: 1 }, position: { x: 0, y: 0, z: 0 }, orientationDegrees: 0, color: "light_bluish_gray", ...overrides };
}

describe("createLegoPartsList", () => {
  it("groups matching parts regardless of orientation and counts their quantities", () => {
    const result = createLegoPartsList(model([placement(), placement({ position: { x: 2, y: 0, z: 0 }, orientationDegrees: 90 })]));
    expect(result).toEqual({ valid: true, totalPartCount: 2, uniquePartTypeCount: 1, parts: [expect.objectContaining({ quantity: 2 })] });
  });

  it("keeps different dimensions and colors in separate groups", () => {
    const result = createLegoPartsList(model([placement(), placement({ brickType: "brick_1x4", dimensions: { lengthStuds: 1, widthStuds: 4, heightBricks: 1 } }), placement({ color: "blue" })]));
    expect(result.valid && result.parts).toHaveLength(3);
  });

  it("sorts by footprint, dimensions, brick type, then color", () => {
    const result = createLegoPartsList(model([placement({ brickType: "brick_b", dimensions: { lengthStuds: 2, widthStuds: 2, heightBricks: 1 }, color: "red" }), placement({ brickType: "brick_a", dimensions: { lengthStuds: 2, widthStuds: 2, heightBricks: 1 }, color: "blue" }), placement({ brickType: "brick_1x4", dimensions: { lengthStuds: 1, widthStuds: 4, heightBricks: 1 } }), placement()]));
    expect(result.valid && result.parts.map((part) => `${part.brickType}:${part.color}`)).toEqual(["brick_2x4:light_bluish_gray", "brick_a:blue", "brick_b:red", "brick_1x4:light_bluish_gray"]);
  });

  it("detects a part count mismatch", () => {
    expect(createLegoPartsList(model([placement()], 2))).toEqual({ valid: false });
  });
});

describe("serializePartsListCsv", () => {
  it("writes a header, deterministic rows, and escaped values", () => {
    expect(serializePartsListCsv([{ brickType: "brick_2x4", lengthStuds: 2, widthStuds: 4, heightBricks: 1, color: "light_bluish_gray", quantity: 3 }])).toBe("Part,Length Studs,Width Studs,Height Bricks,Color,Quantity\r\n2×4 brick,2,4,1,Light Bluish Gray,3");
    expect(serializePartsListCsv([{ brickType: "brick_2x4", lengthStuds: 2, widthStuds: 4, heightBricks: 1, color: "red,blue", quantity: 1 }])).toContain('"Red,Blue"');
  });
});
