import { useQuery } from "@tanstack/react-query";

import { getProfile } from "../api/client";

export function useProfile(accessToken: string, userId: string) {
  return useQuery({
    queryKey: ["profile", userId],
    queryFn: ({ signal }) => getProfile(accessToken, signal),
  });
}
