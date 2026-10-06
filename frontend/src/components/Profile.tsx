import type { Session } from "@supabase/supabase-js";

import { useProfile } from "../hooks/useProfile";

interface ProfileProps {
  session: Session;
  onSignOut: () => void;
}

export function Profile({ session, onSignOut }: ProfileProps) {
  const profile = useProfile(session.access_token, session.user.id);

  return (
    <section className="auth-card" aria-labelledby="profile-title">
      <p className="eyebrow">Signed in</p>
      <h1 id="profile-title">Your profile</h1>
      {profile.isPending ? <p className="summary">Loading your profile…</p> : null}
      {profile.isError ? (
        <div className="profile-error" role="alert">
          <p>We could not load your profile.</p>
          <button className="text-button" type="button" onClick={() => void profile.refetch()}>
            Try again
          </button>
        </div>
      ) : null}
      {profile.data ? (
        <dl className="profile-details">
          {profile.data.avatarUrl ? (
            <img className="avatar" src={profile.data.avatarUrl} alt="Profile" />
          ) : null}
          <div>
            <dt>User ID</dt>
            <dd>{profile.data.id}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{profile.data.email ?? "Not available"}</dd>
          </div>
          {profile.data.displayName ? (
            <div>
              <dt>Name</dt>
              <dd>{profile.data.displayName}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      <button className="button button--secondary" type="button" onClick={onSignOut}>
        Sign out
      </button>
    </section>
  );
}
