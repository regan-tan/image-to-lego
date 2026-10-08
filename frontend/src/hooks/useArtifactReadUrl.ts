import { useQuery } from "@tanstack/react-query";

import { getArtifactReadUrl } from "../api/client";

// Fetch a new link a little before the old one expires, so a remounted image never uses a dead link.
const READ_URL_REFRESH_MARGIN_MS = 60_000;
// Browser timers overflow above ~24.8 days; cap freshness well below that for long-lived links.
const MAX_READ_URL_STALE_MS = 60 * 60 * 1000;

/** Read-only link for showing a private photo or model; `null` skips the request. */
export function useArtifactReadUrl(accessToken: string, userId: string, artifactId: string | null) {
  return useQuery({
    queryKey: ["artifact-read-url", userId, artifactId],
    queryFn: ({ signal }) => getArtifactReadUrl(accessToken, artifactId ?? "", {}, signal),
    enabled: artifactId !== null,
    staleTime: (query) => {
      if (!query.state.data) {
        return 0;
      }
      const msUntilRefresh = Date.parse(query.state.data.expiresAt) - Date.now() - READ_URL_REFRESH_MARGIN_MS;
      return Math.min(Math.max(msUntilRefresh, 0), MAX_READ_URL_STALE_MS);
    },
  });
}
