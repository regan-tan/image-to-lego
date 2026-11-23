import { useQuery } from "@tanstack/react-query";

import { getCredits } from "../api/client";

export const creditsQueryKey = (userId: string) => ["credits", userId] as const;

export function useCredits(accessToken: string, userId: string) {
  return useQuery({
    queryKey: creditsQueryKey(userId),
    queryFn: ({ signal }) => getCredits(accessToken, signal),
  });
}
