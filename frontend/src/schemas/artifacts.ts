import { z } from "zod";

export const artifactReadUrlSchema = z.object({
  url: z.string().url(),
  expiresAt: z.string(),
});

export type ArtifactReadUrl = z.infer<typeof artifactReadUrlSchema>;
