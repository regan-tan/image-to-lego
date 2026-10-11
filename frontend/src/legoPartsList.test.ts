import { describe, expect, it } from "vitest";

import { aggregateLegoPlacements, createLegoPartsList, serializePartsListCsv } from "./legoPartsList";
import type { LegoModel } from "./schemas/legoModels";

function model(placements: LegoModel["placements"], partCount = placements.length): LegoModel {
  return { partCount, dimensions: { widthStuds: 4, depthStuds: 4, heightBricks: 2, widthMm: 32, depthMm: 32, heightMm: 19.2 }, metadata: { algorithmVersion: "test", sourceSha256: "a", targetParts: 10, occupiedCellCount: 1, gridSize: { widthStuds: 4, depthStuds: 4, heightBricks: 2 }, candidateCount: 1, occupancyMode: "test" }, placements };
}

function placement(overrides: Partial<LegoModel["placements"][number]> = {}): LegoModel["placements"][number] {
  return { brickType: "brick_2x4", partId: "3001", partName: "Brick 2 x 4", dimensions: { lengthStuds: 2, widthStuds: 4, heightBricks: 1 }, position: { x: 0, y: 0, z: 0 }, orientationDegrees: 0, color: "light_bluish_gray", ...overrides };
}

describe("createLegoPartsList", () => {
  it("groups matching real parts regardless of orientation and counts their quantities", () => {
    const result = createLegoPartsList(model([placement(), placement({ position: { x: 2, y: 0, z: 0 }, orientationDegrees: 90 })]));
    expect(result).toEqual({ valid: true, totalPartCount: 2, uniquePartTypeCount: 1, parts: [expect.objectContaining({ partId: "3001", partName: "Brick 2 x 4", quantity: 2 })] });
  });

  it("groups the BOM by real part ID and color", () => {
    const result = createLegoPartsList(model([placement({ colorId: "ldraw:71" }), placement({ position: { x: 2, y: 0, z: 0 }, colorId: "ldraw:71" }), placement({ color: "blue", colorId: "ldraw:1" })]));
    expect(result.valid && result.parts).toEqual(expect.arrayContaining([
      expect.objectContaining({ partId: "3001", colorId: "ldraw:71", quantity: 2 }),
      expect.objectContaining({ partId: "3001", colorId: "ldraw:1", quantity: 1 }),
    ]));
  });

  it("detects a part count mismatch", () => {
    expect(createLegoPartsList(model([placement()], 2))).toEqual({ valid: false });
  });
});

describe("aggregateLegoPlacements", () => {
  it("uses the same grouping without requiring a complete model", () => {
    expect(aggregateLegoPlacements([placement(), placement({ orientationDegrees: 90, position: { x: 2, y: 0, z: 0 } })])).toEqual([expect.objectContaining({ quantity: 2 })]);
  });
});

describe("serializePartsListCsv", () => {
  it("writes real part identity, color, and quantity", () => {
    expect(serializePartsListCsv([{ brickType: "brick_2x4", partId: "3001", partName: "Brick 2 x 4", lengthStuds: 2, widthStuds: 4, heightPlates: 3, color: "light_bluish_gray", colorId: "ldraw:71", colorName: "Light Bluish Gray", quantity: 3 }])).toBe("Part ID,Part Name,Color,Color ID,Quantity\r\n3001,Brick 2 x 4,Light Bluish Gray,ldraw:71,3");
    expect(serializePartsListCsv([{ brickType: "plate_2x4", partId: "3020", partName: "Plate 2 x 4", lengthStuds: 2, widthStuds: 4, heightPlates: 1, color: "red,blue", quantity: 1 }])).toContain('3020,Plate 2 x 4,"Red,Blue",,1');
  });
});
