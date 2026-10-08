import { Link } from "react-router-dom";

import { useAppLayout } from "../components/appLayoutContext";
import { ArrowLeftIcon } from "../components/Icons";
import { useProfile } from "../hooks/useProfile";

export function ProfilePage() {
  const { session } = useAppLayout();
  const profile = useProfile(session.access_token, session.user.id);

  return (
    <div className="page__container page__container--narrow">
      <Link to="/" className="back-link">
        <ArrowLeftIcon size={16} />
        All projects
      </Link>
      <div className="page-heading">
        <h1>Profile</h1>
      </div>
      <section className="card" aria-label="Account details">
        {profile.isPending ? <p className="status status--pending" role="status">Loading your profile…</p> : null}
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
            {profile.data.displayName ? (
              <div>
                <dt>Name</dt>
                <dd>{profile.data.displayName}</dd>
              </div>
            ) : null}
            <div>
              <dt>Email</dt>
              <dd>{profile.data.email ?? "Not available"}</dd>
            </div>
            <div>
              <dt>User ID</dt>
              <dd>{profile.data.id}</dd>
            </div>
          </dl>
        ) : null}
      </section>
    </div>
  );
}
