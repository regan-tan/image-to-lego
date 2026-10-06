import type { Session } from "@supabase/supabase-js";

import { AuthenticationForm } from "../components/AuthenticationForm";

interface LoginPageProps {
  onAuthenticated: (session: Session) => void;
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  return (
    <main className="shell">
      <AuthenticationForm mode="login" onAuthenticated={onAuthenticated} />
    </main>
  );
}
