import { z } from "zod";

export const conversionStatusSchema = z.enum(["queued", "running", "succeeded", "failed", "canceled"]);
export type ConversionStatus = z.infer<typeof conversionStatusSchema>;

export const conversionSchema = z.object({
  jobId: z.string().uuid(),
  projectId: z.string().uuid(),
  type: z.literal("conversion"),
  status: conversionStatusSchema,
  outputArtifactId: z.string().uuid().nullable().optional(),
  errorCode: z.string().nullable().optional(),
  errorMessage: z.string().nullable().optional(),
});

export type Conversion = z.infer<typeof conversionSchema>;
