import { Link } from "react-router-dom";

import { useAppLayout } from "../components/appLayoutContext";
import { ArrowLeftIcon } from "../components/Icons";
import { useProfile } from "../hooks/useProfile";

export function ProfilePage() {
  const { session } = useAppLayout();
  const profile = useProfile(session.access_token, session.user.id);
  const profileName = profile.data?.displayName ?? profile.data?.email?.split("@")[0] ?? "Your workspace";
  const initials = profileName.slice(0, 2).toUpperCase();

  return (
    <div className="page__container profile-page">
      <Link to="/workspace" className="back-link"><ArrowLeftIcon size={16} />All projects</Link>
      <div className="page-heading"><div><p className="eyebrow">Your account</p><h1>Account &amp; preferences.</h1><p className="page-heading__meta">Manage the details associated with your creative workspace.</p></div></div>
      <div className="profile-layout"><div>
        <section className="card profile-card" aria-label="Account details">
          {profile.isPending ? <p className="status status--pending" role="status">Loading your profile…</p> : null}
          {profile.isError ? <div className="profile-error" role="alert"><p>We could not load your profile.</p><button className="text-button" type="button" onClick={() => void profile.refetch()}>Try again</button></div> : null}
          {profile.data ? <><h2>Profile information</h2><p>The details associated with your Image to LEGO account.</p><div className="profile-identity">{profile.data.avatarUrl ? <img className="avatar" src={profile.data.avatarUrl} alt="Profile" /> : <span className="avatar avatar--initials" aria-hidden="true">{initials}</span>}<div><strong>{profileName}</strong><span>Account profile information</span></div></div><dl className="profile-details">{profile.data.displayName ? <div><dt>Display name</dt><dd>{profile.data.displayName}</dd></div> : null}<div><dt>Email address</dt><dd>{profile.data.email ?? "Not available"}</dd></div></dl></> : null}
        </section>
        <section className="card security-card"><h2>Privacy &amp; security</h2><p>Your project files are private and associated with your account.</p><dl><div><dt>Authentication provider</dt><dd>Supabase Auth</dd></div><div><dt>Projects visibility</dt><dd>Private by default</dd></div></dl></section>
      </div><aside className="card profile-aside"><h2>Everything in one place.</h2><p>Build new ideas, revisit previous models, and pick up right where you left off.</p><Link className="button button--yellow" to="/workspace">Return to projects →</Link><hr /><h2>Need a little help?</h2><p>Explore the step-by-step guide to using the creative studio.</p></aside></div>
    </div>
  );
}
