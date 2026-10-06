import { z } from "zod";

export const uploadInitiationSchema = z.object({
  uploadId: z.string().uuid(),
  projectId: z.string().uuid(),
  status: z.literal("pending"),
  uploadUrl: z.string().url(),
  uploadUrlExpiresAt: z.string(),
  requiredHeaders: z.record(z.string(), z.string()),
});

export const uploadCompletionSchema = z.object({
  uploadId: z.string().uuid(),
  projectId: z.string().uuid(),
  status: z.literal("ready"),
});

export type UploadInitiation = z.infer<typeof uploadInitiationSchema>;
export type UploadCompletion = z.infer<typeof uploadCompletionSchema>;
