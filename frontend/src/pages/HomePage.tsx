import type { Session } from "@supabase/supabase-js";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Profile } from "../components/Profile";
import { ProjectWorkspace } from "../components/ProjectWorkspace";
import { supabase } from "../lib/supabase";

interface HomePageProps {
  session: Session;
  onSignedOut: () => void;
}

export function HomePage({ session, onSignedOut }: HomePageProps) {
  const navigate = useNavigate();
  const [signOutError, setSignOutError] = useState<string | null>(null);

  async function handleSignOut() {
    const client = supabase;
    if (!client) {
      return;
    }

    setSignOutError(null);
    const { error } = await client.auth.signOut();
    if (error) {
      setSignOutError("We could not sign you out. Please try again.");
      return;
    }
    onSignedOut();
    navigate("/login", { replace: true });
  }

  return (
    <main className="shell">
      <div className="home-grid">
        <Profile session={session} onSignOut={() => void handleSignOut()} />
        <ProjectWorkspace accessToken={session.access_token} userId={session.user.id} />
        {signOutError ? <p className="form-error" role="alert">{signOutError}</p> : null}
      </div>
    </main>
  );
}
