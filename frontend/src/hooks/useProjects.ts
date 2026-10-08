import { useQuery } from "@tanstack/react-query";

import { getProjects } from "../api/client";

export function projectsQueryKey(userId: string) {
  return ["projects", userId] as const;
}

export function useProjects(accessToken: string, userId: string) {
  return useQuery({
    queryKey: projectsQueryKey(userId),
    queryFn: ({ signal }) => getProjects(accessToken, signal),
  });
}
