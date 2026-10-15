import { z } from "zod";

const dimensionsSchema = z.object({
  widthStuds: z.number(),
  depthStuds: z.number(),
  heightBricks: z.number().optional(),
  heightPlates: z.number().optional(),
}).refine((dimensions) => dimensions.heightBricks !== undefined || dimensions.heightPlates !== undefined, {
  message: "A LEGO model height must use bricks or plates.",
});

const partDimensionsSchema = z.object({
  lengthStuds: z.number(),
  widthStuds: z.number(),
  heightBricks: z.number().optional(),
  heightPlates: z.number().optional(),
}).refine((dimensions) => dimensions.heightBricks !== undefined || dimensions.heightPlates !== undefined, {
  message: "A LEGO part height must use bricks or plates.",
});

export const legoModelSchema = z.object({
  partCount: z.number().int().nonnegative(),
  dimensions: dimensionsSchema.extend({ widthMm: z.number(), depthMm: z.number(), heightMm: z.number() }),
  metadata: z.object({
    algorithmVersion: z.string(),
    sourceSha256: z.string(),
    targetParts: z.number().optional(),
    occupiedCellCount: z.number(),
    gridSize: dimensionsSchema,
    candidateCount: z.number(),
    occupancyMode: z.string(),
    partColorVerificationVersion: z.string().optional(),
  }),
  placements: z.array(z.object({
    brickType: z.string(),
    partId: z.string().optional(),
    partName: z.string().optional(),
    shape: z.enum(["rectangular", "slope_33_3x1"]).optional(),
    geometryAsset: z.string().optional(),
    dimensions: partDimensionsSchema,
    position: z.object({ x: z.number(), y: z.number(), z: z.number() }),
    orientationDegrees: z.union([z.literal(0), z.literal(90), z.literal(180), z.literal(270)]),
    color: z.string(),
    colorId: z.string().optional(),
    colorName: z.string().optional(),
    colorHex: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
    externalIds: z.object({
      bricklink: z.object({
        partId: z.string().nullable(),
        colorId: z.number().int().nullable(),
      }).optional(),
    }).optional(),
    partColorVerified: z.boolean().optional(),
  })),
  instructionSteps: z.array(z.object({
    stepNumber: z.number().int().positive(),
    placementIndices: z.array(z.number().int().nonnegative()).min(1),
  })).optional(),
});

export type LegoModel = z.infer<typeof legoModelSchema>;

export function heightInPlates(dimensions: { heightBricks?: number; heightPlates?: number }): number {
  return dimensions.heightPlates ?? (dimensions.heightBricks ?? 0) * 3;
}
