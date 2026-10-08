import { useQuery } from "@tanstack/react-query";

import { ApiError, getProject, getProjects } from "../api/client";
import { RECONSTRUCTION_POLL_INTERVAL_MS, reconstructionPollInterval } from "../reconstructionPolling";

const MAX_PROJECT_QUERY_RETRIES = 2;

export function projectsQueryKey(userId: string) {
  return ["projects", userId] as const;
}

export function projectQueryKey(userId: string, projectId: string) {
  return ["project", userId, projectId] as const;
}

export function useProjects(accessToken: string, userId: string) {
  return useQuery({
    queryKey: projectsQueryKey(userId),
    queryFn: ({ signal }) => getProjects(accessToken, signal),
    // Keep card badges current only while some generation is still in progress.
    refetchInterval: (query) => (
      query.state.data?.some((project) => project.status === "generating")
        ? RECONSTRUCTION_POLL_INTERVAL_MS
        : false
    ),
  });
}

export function useProject(accessToken: string, userId: string, projectId: string) {
  return useQuery({
    queryKey: projectQueryKey(userId, projectId),
    queryFn: ({ signal }) => getProject(accessToken, projectId, signal),
    refetchInterval: (query) => reconstructionPollInterval(query.state.data?.latestReconstruction?.status),
    retry: (failureCount, error) => !isNotFound(error) && failureCount < MAX_PROJECT_QUERY_RETRIES,
  });
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}
