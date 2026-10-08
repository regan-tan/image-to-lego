import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { isSupabaseConfigured, supabase } from "./lib/supabase";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SignupPage } from "./pages/SignupPage";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState(() => supabase !== null);

  useEffect(() => {
    const client = supabase;
    if (!client) {
      return;
    }

    let isMounted = true;
    void client.auth.getSession().then(
      ({ data }) => {
        if (isMounted) {
          setSession(data.session);
          setIsLoadingSession(false);
        }
      },
      () => {
        if (isMounted) {
          setIsLoadingSession(false);
        }
      },
    );
    const { data } = client.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setIsLoadingSession(false);
    });
    return () => {
      isMounted = false;
      data.subscription.unsubscribe();
    };
  }, []);

  if (!isSupabaseConfigured) {
    return (
      <main className="shell">
        <section className="auth-card" aria-labelledby="configuration-title">
          <p className="eyebrow">Image to LEGO</p>
          <h1 id="configuration-title">Authentication is not configured</h1>
          <p className="summary">
            Set the Supabase URL and publishable key in the frontend environment before signing in.
          </p>
        </section>
      </main>
    );
  }

  if (isLoadingSession) {
    return (
      <main className="shell">
        <p className="status status--pending">Loading session…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage onAuthenticated={(newSession) => setSession(newSession)} />} />
        <Route path="/signup" element={<SignupPage onAuthenticated={(newSession) => setSession(newSession)} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<AppLayout session={session} onSignedOut={() => setSession(null)} />}>
        <Route index element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
