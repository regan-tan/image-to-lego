import type { Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { isSupabaseConfigured, supabase } from "./lib/supabase";
import { idleSessionKey, isSessionIdle, watchIdleSession } from "./idleSession";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SignupPage } from "./pages/SignupPage";

export default function App() {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [signOutFailed, setSignOutFailed] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(() => supabase !== null);

  const expireSession = useCallback(() => {
    setSession(null);
    setSessionExpired(true);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    const client = supabase;
    if (!client) {
      return;
    }

    let isMounted = true;

    function restoreSession(nextSession: Session | null) {
      if (!isMounted) return;
      if (nextSession && isSessionIdle(nextSession)) {
        expireSession();
      } else {
        // Supabase can update session.user in place when metadata changes.
        setSession(nextSession ? { ...nextSession } : null);
        if (nextSession) setSessionExpired(false);
        if (!nextSession) queryClient.clear();
      }
      setIsLoadingSession(false);
    }

    void client.auth.getSession().then(
      ({ data }) => {
        restoreSession(data.session);
      },
      () => {
        if (isMounted) {
          setIsLoadingSession(false);
        }
      },
    );
    const { data } = client.auth.onAuthStateChange((_event, nextSession) => {
      restoreSession(nextSession);
    });
    return () => {
      isMounted = false;
      data.subscription.unsubscribe();
    };
  }, [queryClient, expireSession]);

  useEffect(() => {
    if (!session) return;
    return watchIdleSession(session, expireSession);
  }, [session, expireSession]);

  useEffect(() => {
    if (!sessionExpired || !supabase) return;
    let isMounted = true;
    // Run outside onAuthStateChange to avoid taking the auth lock recursively.
    void supabase.auth.signOut({ scope: "local" }).then(
      ({ error }) => {
        if (isMounted) setSignOutFailed(Boolean(error));
      },
      () => {
        if (isMounted) setSignOutFailed(true);
      },
    );
    return () => {
      isMounted = false;
    };
  }, [sessionExpired]);

  function handleAuthenticated(nextSession: Session) {
    localStorage.setItem(idleSessionKey(nextSession), String(Date.now()));
    setSessionExpired(false);
    setSignOutFailed(false);
    setSession(nextSession);
  }

  return (
    <>
    {sessionExpired && !session ? <p className="status" role="status">Your session expired after 10 minutes of inactivity. Please sign in again.</p> : null}
    {sessionExpired && signOutFailed ? <p className="form-error" role="alert">We could not finish signing out. Reconnect and reload to try again. Your workspace remains locked.</p> : null}
    <Routes>
      <Route path="/" element={<LandingPage isAuthenticated={session !== null} />} />
      {isSupabaseConfigured ? (
        <>
          <Route path="login" element={session ? <Navigate to="/workspace" replace /> : <LoginPage onAuthenticated={handleAuthenticated} />} />
          <Route path="signup" element={session ? <Navigate to="/workspace" replace /> : <SignupPage onAuthenticated={handleAuthenticated} />} />
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
    </>
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
