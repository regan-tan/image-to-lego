import { z } from "zod";

import { reconstructionStatusSchema } from "./reconstructions";

export const projectStatusSchema = z.enum([
  "needs_photo",
  "photo_ready",
  "generating",
  "model_ready",
  "failed",
]);

export const projectSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: projectStatusSchema,
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const projectsSchema = z.array(projectSchema);

const sourceImageSchema = z.object({
  artifactId: z.string().uuid(),
  mimeType: z.string(),
  sizeBytes: z.number().int().nonnegative(),
  createdAt: z.string(),
});

const latestReconstructionSchema = z.object({
  jobId: z.string().uuid(),
  status: reconstructionStatusSchema,
  outputArtifactId: z.string().uuid().nullable(),
  errorCode: z.string().nullable(),
  errorMessage: z.string().nullable(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const projectDetailSchema = projectSchema.extend({
  sourceImage: sourceImageSchema.nullable(),
  latestReconstruction: latestReconstructionSchema.nullable(),
});

export type ProjectStatus = z.infer<typeof projectStatusSchema>;
export type Project = z.infer<typeof projectSchema>;
export type ProjectDetail = z.infer<typeof projectDetailSchema>;
