import type { Session } from "@supabase/supabase-js";
import { useState } from "react";
import { Link, Outlet, useNavigate } from "react-router-dom";

import { supabase } from "../lib/supabase";
import { AccountMenu } from "./AccountMenu";
import type { AppLayoutContext } from "./appLayoutContext";
import { HowItWorksDialog } from "./HowItWorksDialog";
import { HelpIcon, LogoMark } from "./Icons";
import { NewProjectDialog } from "./NewProjectDialog";

interface AppLayoutProps {
  session: Session;
  onSignedOut: () => void;
}

export function AppLayout({ session, onSignedOut }: AppLayoutProps) {
  const navigate = useNavigate();
  const [isHowItWorksOpen, setIsHowItWorksOpen] = useState(false);
  const [isNewProjectOpen, setIsNewProjectOpen] = useState(false);
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
      <header className="app-header">
        <div className="app-header__inner">
          <Link to="/" className="app-header__brand" aria-label="Image to LEGO, all projects">
            <LogoMark />
            <span className="app-header__brand-name">Image to LEGO</span>
          </Link>
          <div className="app-header__actions">
            <button type="button" className="header-link" onClick={layoutContext.openHowItWorks}>
              <HelpIcon />
              How it works
            </button>
            <AccountMenu email={session.user.email} onSignOut={() => void handleSignOut()} />
          </div>
        </div>
      </header>
      {signOutError ? <p className="form-error page-alert" role="alert">{signOutError}</p> : null}
      <main className="page">
        <Outlet context={layoutContext} />
      </main>
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
