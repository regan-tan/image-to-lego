import { profileResponseSchema, type ProfileResponse } from "../schemas/profile";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export async function getProfile(accessToken: string, signal?: AbortSignal): Promise<ProfileResponse> {
  const response = await fetch(`${apiBaseUrl}/api/v1/profile`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Profile request failed with status ${response.status}`);
  }

  return profileResponseSchema.parse(await response.json());
}

