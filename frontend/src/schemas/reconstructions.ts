import { z } from "zod";

export const reconstructionStatusSchema = z.enum(["queued", "running", "succeeded", "failed", "canceled"]);

export const reconstructionSchema = z.object({
  jobId: z.string().uuid(),
  projectId: z.string().uuid(),
  type: z.literal("reconstruction"),
  status: reconstructionStatusSchema,
});

export type Reconstruction = z.infer<typeof reconstructionSchema>;
