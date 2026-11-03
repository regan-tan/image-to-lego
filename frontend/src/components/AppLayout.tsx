import type { Session } from "@supabase/supabase-js";
import { useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { supabase } from "../lib/supabase";
import { AccountMenu } from "./AccountMenu";
import type { AppLayoutContext } from "./appLayoutContext";
import { HowItWorksDialog } from "./HowItWorksDialog";
import { LogoMark, PlusIcon } from "./Icons";
import { Dialog } from "./Dialog";
import { NewProjectDialog } from "./NewProjectDialog";

interface AppLayoutProps {
  session: Session;
  onSignedOut: () => void;
}

export function AppLayout({ session, onSignedOut }: AppLayoutProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isHowItWorksOpen, setIsHowItWorksOpen] = useState(false);
  const [isNewProjectOpen, setIsNewProjectOpen] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const [isSignOutOpen, setIsSignOutOpen] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const displayName: unknown = session.user.user_metadata?.full_name ?? session.user.user_metadata?.name;

  async function handleSignOut() {
    const client = supabase;
    if (!client || isSigningOut) {
      return;
    }

    setSignOutError(null);
    setIsSigningOut(true);
    try {
      const { error } = await client.auth.signOut();
      if (error) {
        setSignOutError("We could not sign you out. Please try again.");
        return;
      }
      onSignedOut();
      navigate("/login", { replace: true });
    } catch {
      setSignOutError("We could not sign you out. Please try again.");
    } finally {
      setIsSigningOut(false);
    }
  }

  const layoutContext: AppLayoutContext = {
    session,
    openHowItWorks: () => setIsHowItWorksOpen(true),
    openNewProject: () => {
      setIsHowItWorksOpen(false);
      setIsNewProjectOpen(true);
    },
  };

  return (
    <div className="app">
      <div className="app-workspace">
        <aside className="app-sidebar" aria-label="Workspace navigation">
          <Link className="app-sidebar__brand" to="/" aria-label="Image to LEGO home"><LogoMark /> <span>IMAGE → LEGO</span></Link>
          <p className="app-sidebar__section">Workspace</p>
          <nav className="app-sidebar__nav">
            <Link to="/workspace" className={location.pathname === "/workspace" ? "is-active" : ""} aria-current={location.pathname === "/workspace" ? "page" : undefined}>All projects</Link>
            <button type="button" aria-label="Create a new project" onClick={layoutContext.openNewProject}><PlusIcon size={16} /> New project</button>
          </nav>
          <AccountMenu
            email={session.user.email}
            name={typeof displayName === "string" ? displayName : undefined}
            onAbout={layoutContext.openHowItWorks}
            onSignOut={() => {
              setSignOutError(null);
              setIsSignOutOpen(true);
            }}
          />
        </aside>
        <main className="page"><Outlet context={layoutContext} /></main>
      </div>
      <Dialog isOpen={isSignOutOpen} onClose={() => {
        if (!isSigningOut) setIsSignOutOpen(false);
      }} title="Sign out?" description="Are you sure you want to sign out of your account?">
        {signOutError ? <p className="form-error" role="alert">{signOutError}</p> : null}
        <div className="dialog__actions">
          <button type="button" className="button button--secondary" disabled={isSigningOut} onClick={() => setIsSignOutOpen(false)}>No, stay signed in</button>
          <button type="button" className="button" disabled={isSigningOut} onClick={() => void handleSignOut()}>{isSigningOut ? "Signing out…" : "Yes, sign out"}</button>
        </div>
      </Dialog>
      <HowItWorksDialog
        isOpen={isHowItWorksOpen}
        onClose={() => setIsHowItWorksOpen(false)}
        onStartProject={layoutContext.openNewProject}
      />
      <NewProjectDialog
        isOpen={isNewProjectOpen}
        onClose={() => setIsNewProjectOpen(false)}
        accessToken={session.access_token}
        userId={session.user.id}
      />
    </div>
  );
}
