import { z } from "zod";

const reconstructionStatusSchema = z.enum(["queued", "running", "succeeded", "failed", "canceled"]);

export const reconstructionSchema = z.object({
  jobId: z.string().uuid(),
  projectId: z.string().uuid(),
  type: z.literal("reconstruction"),
  status: reconstructionStatusSchema,
});

export const jobSchema = reconstructionSchema.extend({
  outputArtifactId: z.string().uuid().nullable(),
  errorCode: z.string().nullable(),
  errorMessage: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type Reconstruction = z.infer<typeof reconstructionSchema>;
export type ReconstructionJob = z.infer<typeof jobSchema>;
