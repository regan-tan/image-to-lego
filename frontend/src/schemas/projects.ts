import { z } from "zod";

export const projectSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const projectsSchema = z.array(projectSchema);

export type Project = z.infer<typeof projectSchema>;
