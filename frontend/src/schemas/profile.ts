import { z } from "zod";

export const profileResponseSchema = z.object({
  id: z.string(),
  email: z.string().email().nullable(),
  displayName: z.string().nullable(),
  avatarUrl: z.string().nullable(),
});

export type ProfileResponse = z.infer<typeof profileResponseSchema>;
