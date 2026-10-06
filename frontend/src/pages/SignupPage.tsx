import type { Session } from "@supabase/supabase-js";

import { AuthenticationForm } from "../components/AuthenticationForm";

interface SignupPageProps {
  onAuthenticated: (session: Session) => void;
}

export function SignupPage({ onAuthenticated }: SignupPageProps) {
  return (
    <main className="shell">
      <AuthenticationForm mode="signup" onAuthenticated={onAuthenticated} />
    </main>
  );
}
