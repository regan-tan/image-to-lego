import { describe, expect, it } from "vitest";

import {
  aggregateLegoPlacements,
  createLegoPartsList,
  createPurchaseReadyPartsList,
  serializePartsListCsv,
  serializePurchaseReadyPartsCsv,
} from "./legoPartsList";
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
    const result = createLegoPartsList(model([placement({ colorId: "ldraw:71", partColorVerified: true }), placement({ position: { x: 2, y: 0, z: 0 }, colorId: "ldraw:71", partColorVerified: true }), placement({ color: "blue", colorId: "ldraw:1", partColorVerified: true })]));
    expect(result.valid && result.parts).toEqual(expect.arrayContaining([
      expect.objectContaining({ partId: "3001", colorId: "ldraw:71", partColorVerified: true, quantity: 2 }),
      expect.objectContaining({ partId: "3001", colorId: "ldraw:1", quantity: 1 }),
    ]));
  });

  it("includes a slope under its canonical part ID and color", () => {
    const slope = placement({
      brickType: "slope_1x3",
      partId: "4286",
      partName: "Slope 33 3 x 1",
      shape: "slope_33_3x1",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
      color: "red",
      colorId: "ldraw:4",
      colorName: "Red",
    });

    expect(createLegoPartsList(model([slope]))).toEqual({
      valid: true,
      totalPartCount: 1,
      uniquePartTypeCount: 1,
      parts: [expect.objectContaining({ partId: "4286", partName: "Slope 33 3 x 1", colorId: "ldraw:4", quantity: 1 })],
    });
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
    expect(serializePartsListCsv([{ brickType: "brick_2x4", partId: "3001", partName: "Brick 2 x 4", lengthStuds: 2, widthStuds: 4, heightPlates: 3, color: "light_bluish_gray", colorId: "ldraw:71", colorName: "Light Bluish Gray", partColorVerified: true, quantity: 3 }])).toBe("Part ID,Part Name,Color,Color ID,Verified part/color,Quantity\r\n3001,Brick 2 x 4,Light Bluish Gray,ldraw:71,Verified,3");
    expect(serializePartsListCsv([{ brickType: "plate_2x4", partId: "3020", partName: "Plate 2 x 4", lengthStuds: 2, widthStuds: 4, heightPlates: 1, color: "red,blue", quantity: 1 }])).toContain('3020,Plate 2 x 4,"Red,Blue",,Unresolved,1');
  });
});

describe("createPurchaseReadyPartsList", () => {
  const algorithmVersion = "surface-grid-v4";
  const verificationVersion = "catalogue-v1";

  function verifiedPart(overrides: Partial<ReturnType<typeof aggregateLegoPlacements>[number]> = {}) {
    return {
      brickType: "brick_2x4",
      partId: "3001",
      partName: "Brick 2 x 4",
      lengthStuds: 4,
      widthStuds: 2,
      heightPlates: 3,
      color: "red",
      colorId: "ldraw:4",
      colorName: "Red",
      partColorVerified: true,
      quantity: 2,
      externalIds: { bricklink: { partId: "3001", colorId: 5 } },
      ...overrides,
    };
  }

  it("keeps one exact verified part/color row with the BOM quantity and authoritative IDs", () => {
    const result = createPurchaseReadyPartsList([verifiedPart()], algorithmVersion, verificationVersion);

    expect(result).toEqual({
      parts: [{
        partId: "3001",
        colorId: "ldraw:4",
        quantity: 2,
        partName: "Brick 2 x 4",
        colorName: "Red",
        partColorVerified: true,
        partColorVerificationVersion: verificationVersion,
        externalIds: { bricklink: { partId: "3001", colorId: 5 } },
      }],
      unresolvedParts: [],
    });
  });

  it("keeps different canonical colors in separate deterministic rows", () => {
    const first = createPurchaseReadyPartsList([
      verifiedPart({ color: "blue", colorId: "ldraw:1", colorName: "Blue", externalIds: { bricklink: { partId: "3001", colorId: 7 } } }),
      verifiedPart(),
    ], algorithmVersion, verificationVersion);
    const second = createPurchaseReadyPartsList([...first.parts.map((part) => verifiedPart({
      color: part.colorName.toLowerCase(),
      colorId: part.colorId,
      colorName: part.colorName,
      externalIds: part.externalIds,
    }))].reverse(), algorithmVersion, verificationVersion);

    expect(first.parts.map((part) => part.colorId)).toEqual(["ldraw:1", "ldraw:4"]);
    expect(serializePurchaseReadyPartsCsv(first.parts)).toBe(serializePurchaseReadyPartsCsv(second.parts));
  });

  it("excludes unverified, missing-identity, and legacy rows instead of exporting them", () => {
    const result = createPurchaseReadyPartsList([
      verifiedPart({ partColorVerified: false }),
      verifiedPart({ partId: undefined }),
      verifiedPart({ colorId: undefined }),
    ], algorithmVersion, verificationVersion);

    expect(result.parts).toEqual([]);
    expect(result.unresolvedParts.map((part) => part.reason)).toEqual([
      "unverified_part_color",
      "missing_part_id",
      "missing_color_id",
    ]);
  });

  it("keeps historical inventory visible but unresolved when verification metadata is absent", () => {
    const result = createPurchaseReadyPartsList([
      verifiedPart({ partColorVerified: undefined }),
    ], algorithmVersion, undefined);

    expect(result.parts).toEqual([]);
    expect(result.unresolvedParts[0]?.reason).toBe("missing_verification_metadata");
  });

  it("rejects a v4 row when its catalog verification version is missing", () => {
    const result = createPurchaseReadyPartsList([verifiedPart()], algorithmVersion, undefined);

    expect(result.parts).toEqual([]);
    expect(result.unresolvedParts[0]?.reason).toBe("missing_verification_version");
  });

  it("leaves missing external IDs blank without fabricating a mapping", () => {
    const result = createPurchaseReadyPartsList([
      verifiedPart({ externalIds: undefined }),
    ], algorithmVersion, verificationVersion);

    expect(result.parts[0]?.externalIds).toEqual({ bricklink: { partId: null, colorId: null } });
  });
});

describe("purchase-ready algorithm compatibility", () => {
  const verificationVersion = "catalogue-v1";

  function verifiedPart() {
    return {
      brickType: "brick_2x4",
      partId: "3001",
      partName: "Brick 2 x 4",
      lengthStuds: 4,
      widthStuds: 2,
      heightPlates: 3,
      color: "red",
      colorId: "ldraw:4",
      colorName: "Red",
      partColorVerified: true,
      quantity: 2,
      externalIds: { bricklink: { partId: "3001", colorId: 5 } },
    };
  }

  it("rejects persisted v3 verification metadata", () => {
    const parts = [verifiedPart()];
    const result = createPurchaseReadyPartsList(parts, "surface-grid-v3", verificationVersion);

    expect(result.parts).toEqual([]);
    expect(result.unresolvedParts[0]?.reason).toBe("unsupported_algorithm_version");
    expect(serializePartsListCsv(parts)).toContain("3001,Brick 2 x 4,Red,ldraw:4,Verified,2");
  });

  it.each([undefined, "surface-grid-v5", "unknown"])("rejects unsupported algorithm version %s", (version) => {
    const result = createPurchaseReadyPartsList([verifiedPart()], version, verificationVersion);

    expect(result.parts).toEqual([]);
    expect(result.unresolvedParts[0]?.reason).toBe("unsupported_algorithm_version");
  });
});

describe("serializePurchaseReadyPartsCsv", () => {
  it("writes stable headers and escapes sourcing row data", () => {
    const csv = serializePurchaseReadyPartsCsv(createPurchaseReadyPartsList([
      {
        brickType: "plate_2x4",
        partId: "3020",
        partName: "Plate \"2 x 4\"",
        lengthStuds: 4,
        widthStuds: 2,
        heightPlates: 1,
        color: "red",
        colorId: "ldraw:4",
        colorName: "Red, Bright",
        partColorVerified: true,
        quantity: 3,
        externalIds: { bricklink: { partId: "3020", colorId: 5 } },
      },
    ], "surface-grid-v4", "catalogue-v1").parts);

    expect(csv).toBe("Part ID,BrickLink Part ID,Color ID,BrickLink Color ID,Quantity,Part Name,Color Name,Verified part/color,Verification version\r\n3020,3020,ldraw:4,5,3,\"Plate \"\"2 x 4\"\"\",\"Red, Bright\",Verified,catalogue-v1");
  });
});
