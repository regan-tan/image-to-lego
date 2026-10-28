import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { isSupabaseConfigured, supabase } from "./lib/supabase";
import { LandingPage } from "./pages/LandingPage";
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

  return (
    <Routes>
      <Route path="/" element={<LandingPage isAuthenticated={session !== null} />} />
      {isSupabaseConfigured ? (
        <>
          <Route path="login" element={session ? <Navigate to="/workspace" replace /> : <LoginPage onAuthenticated={setSession} />} />
          <Route path="signup" element={session ? <Navigate to="/workspace" replace /> : <SignupPage onAuthenticated={setSession} />} />
          <Route element={<ProtectedApp session={session} isLoadingSession={isLoadingSession} onSignedOut={() => setSession(null)} />}>
            <Route path="workspace" element={<ProjectsPage />} />
            <Route path="projects/:projectId" element={<ProjectPage />} />
            <Route path="profile" element={<ProfilePage />} />
          </Route>
        </>
      ) : (
        <Route path="login" element={<AuthenticationConfiguration />} />
      )}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

interface ProtectedAppProps {
  session: Session | null;
  isLoadingSession: boolean;
  onSignedOut: () => void;
}

function ProtectedApp({ session, isLoadingSession, onSignedOut }: ProtectedAppProps) {
  const location = useLocation();

  if (isLoadingSession) {
    return <main className="shell"><p className="status status--pending">Loading session…</p></main>;
  }
  if (!session) {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to="/login" replace state={{ returnTo }} />;
  }
  return <AppLayout session={session} onSignedOut={onSignedOut} />;
}

function AuthenticationConfiguration() {
  return (
    <main className="shell">
      <section className="auth-card" aria-labelledby="configuration-title">
        <p className="eyebrow">Image to LEGO</p>
        <h1 id="configuration-title">Authentication is not configured</h1>
        <p className="summary">Set the Supabase URL and publishable key in the frontend environment before signing in.</p>
      </section>
    </main>
  );
}
