import { z } from "zod";

const dimensionsSchema = z.object({
  widthStuds: z.number(),
  depthStuds: z.number(),
  heightBricks: z.number(),
});

export const legoModelSchema = z.object({
  partCount: z.number().int().nonnegative(),
  dimensions: dimensionsSchema.extend({ widthMm: z.number(), depthMm: z.number(), heightMm: z.number() }),
  metadata: z.object({
    algorithmVersion: z.string(),
    sourceSha256: z.string(),
    targetParts: z.number(),
    occupiedCellCount: z.number(),
    gridSize: dimensionsSchema,
    candidateCount: z.number(),
    occupancyMode: z.string(),
  }),
  placements: z.array(z.object({
    brickType: z.string(),
    dimensions: z.object({ lengthStuds: z.number(), widthStuds: z.number(), heightBricks: z.number() }),
    position: z.object({ x: z.number(), y: z.number(), z: z.number() }),
    orientationDegrees: z.union([z.literal(0), z.literal(90)]),
    color: z.string(),
  })),
});

export type LegoModel = z.infer<typeof legoModelSchema>;
