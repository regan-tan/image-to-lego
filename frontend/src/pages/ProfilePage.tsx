import { Link } from "react-router-dom";
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useAppLayout } from "../components/appLayoutContext";
import { ArrowLeftIcon } from "../components/Icons";
import { useProfile } from "../hooks/useProfile";
import { supabase } from "../lib/supabase";
import type { ProfileResponse } from "../schemas/profile";

const MAX_DISPLAY_NAME_LENGTH = 80;

export function ProfilePage() {
  const { session } = useAppLayout();
  const profile = useProfile(session.access_token, session.user.id);
  const queryClient = useQueryClient();
  const [draftName, setDraftName] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const displayName = draftName ?? profile.data?.displayName ?? "";
  const hasChanges = displayName.trim() !== (profile.data?.displayName?.trim() ?? "");
  const saveName = useMutation({
    retry: false,
    mutationFn: async (name: string) => {
      if (!supabase) throw new Error("Authentication is unavailable.");
      const { data, error } = await supabase.auth.updateUser({ data: { full_name: name } });
      if (error || !data.user) throw new Error("Display name could not be saved.");
      // The profile API reads JWT metadata, so renew its token after saving the user.
      let refreshFailed: boolean;
      try {
        const refreshed = await supabase.auth.refreshSession();
        refreshFailed = Boolean(refreshed.error || !refreshed.data.session);
      } catch {
        refreshFailed = true;
      }
      return { name, refreshFailed };
    },
    onSuccess: async ({ name }) => {
      const queryKey = ["profile", session.user.id];
      await queryClient.cancelQueries({ queryKey, exact: true });
      queryClient.setQueryData<ProfileResponse>(queryKey, (current) => current ? { ...current, displayName: name } : current);
      setDraftName(null);
    },
  });

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saveName.isPending || !hasChanges) return;
    const name = displayName.trim();
    if (!name || name.length > MAX_DISPLAY_NAME_LENGTH) {
      setNameError(`Enter a display name between 1 and ${MAX_DISPLAY_NAME_LENGTH} characters.`);
      return;
    }
    setNameError(null);
    saveName.mutate(name);
  }
  const profileName = profile.data?.displayName?.trim() || profile.data?.email?.split("@")[0] || "Your account";
  const initials = profileName.split(/\s+/).slice(0, 2).map((word) => word.charAt(0)).join("").toUpperCase();

  return (
    <div className="page__container profile-page">
      <Link to="/workspace" className="back-link"><ArrowLeftIcon size={16} />All projects</Link>
      <header className="profile-page__heading">
        <h1>Profile</h1>
        <p>Your personal details, all in one place.</p>
      </header>
      <section aria-label="Account details">
        {profile.isPending ? <p className="status status--pending" role="status">Loading your profile…</p> : null}
        {profile.isError ? (
          <div className="profile-error" role="alert">
            <p>We could not load your profile.</p>
            <button className="text-button" type="button" onClick={() => void profile.refetch()}>Try again</button>
          </div>
        ) : null}
        {profile.data ? (
          <form onSubmit={handleSave}>
            <dl className="profile-details">
              <div className="profile-details__photo">
                <dt>Profile photo</dt>
                <dd>
                  {profile.data.avatarUrl ? (
                    <img className="profile-avatar" src={profile.data.avatarUrl} alt={`${profileName}'s profile photo`} width="64" height="64" />
                  ) : (
                    <span className="profile-avatar profile-avatar--initials" aria-label={`Profile initials: ${initials}`}>{initials}</span>
                  )}
                </dd>
              </div>
              <div>
                <dt><label htmlFor="profile-display-name">Display name</label></dt>
                <dd>
                  <input id="profile-display-name" className="profile-name-input" type="text" autoComplete="nickname" maxLength={MAX_DISPLAY_NAME_LENGTH} value={displayName} disabled={saveName.isPending} aria-invalid={Boolean(nameError)} aria-describedby={nameError ? "profile-name-error" : undefined} onChange={(event) => {
                    setDraftName(event.target.value);
                    setNameError(null);
                    saveName.reset();
                  }} />
                </dd>
              </div>
              <div>
                <dt>Email address</dt>
                <dd>{profile.data.email ?? "Not available"}</dd>
              </div>
            </dl>
            {nameError ? <p id="profile-name-error" className="form-error" role="alert">{nameError}</p> : null}
            {saveName.isError ? <p className="form-error" role="alert">We could not save your display name. Please try again.</p> : null}
            <div className="profile-actions">
              {saveName.isSuccess ? <p role="status">{saveName.data.refreshFailed ? "Your name was saved, but your session could not refresh. Sign out and back in to refresh your account details." : "Display name saved."}</p> : null}
              <button type="submit" className="button" disabled={!hasChanges || saveName.isPending}>{saveName.isPending ? "Saving…" : "Save changes"}</button>
            </div>
          </form>
        ) : null}
      </section>
    </div>
  );
}
