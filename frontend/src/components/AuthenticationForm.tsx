import type { Session } from "@supabase/supabase-js";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { supabase } from "../lib/supabase";

export type AuthenticationMode = "login" | "signup";

interface AuthenticationFormProps {
  mode: AuthenticationMode;
  onAuthenticated: (session: Session) => void;
}

const RETURN_PATH_STORAGE_KEY = "image-to-lego.return-path";
const DEFAULT_RETURN_PATH = "/workspace";

export function AuthenticationForm({ mode, onAuthenticated }: AuthenticationFormProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const isLogin = mode === "login";
  const hasLegacyReturnPath = searchParams.has("next");
  const legacyReturnPath = safeReturnPath(searchParams.get("next"));
  const stateReturnPath = safeReturnPath(readReturnPath(location.state));
  const storedReturnPath = safeReturnPath(window.sessionStorage.getItem(RETURN_PATH_STORAGE_KEY));
  const returnPath = stateReturnPath ?? legacyReturnPath ?? storedReturnPath ?? DEFAULT_RETURN_PATH;

  useEffect(() => {
    if (returnPath !== DEFAULT_RETURN_PATH) {
      window.sessionStorage.setItem(RETURN_PATH_STORAGE_KEY, returnPath);
    }
    if (hasLegacyReturnPath) {
      navigate(location.pathname, {
        replace: true,
        state: legacyReturnPath ? { returnTo: legacyReturnPath } : undefined,
      });
    }
  }, [hasLegacyReturnPath, legacyReturnPath, location.pathname, navigate, returnPath]);

  function finishAuthentication(session: Session) {
    window.sessionStorage.removeItem(RETURN_PATH_STORAGE_KEY);
    onAuthenticated(session);
    navigate(returnPath, { replace: true });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) return;

    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      if (!isLogin) {
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) {
          setErrorMessage("We could not create your account. Check your details and try again.");
        } else if (data.session) {
          finishAuthentication(data.session);
        } else {
          setPassword("");
          setShowConfirmation(true);
        }
        return;
      }

      const { data, error } = await supabase.auth.signInWithPassword({ email, password });
      if (error || !data.session) {
        setErrorMessage("We could not sign you in. Check your email and password and try again.");
        return;
      }
      finishAuthentication(data.session);
    } catch {
      setErrorMessage("We could not complete sign-in. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleOAuth(provider: "google" | "github") {
    if (!supabase) return;

    setErrorMessage(null);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider,
        options: { redirectTo: new URL(returnPath, window.location.origin).toString() },
      });
      if (error) setErrorMessage("We could not start sign-in. Please try again.");
    } catch {
      setErrorMessage("We could not start sign-in. Please try again.");
    }
  }

  if (showConfirmation) {
    return (
      <main className="shell">
        <section className="auth-confirmation" aria-labelledby="confirmation-title">
          <p className="eyebrow">One more step</p>
          <h1 id="confirmation-title">Check your email</h1>
          <p>We sent a confirmation link to {email}. Confirm your address, then sign in to continue.</p>
          <Link className="button" to="/login" state={{ returnTo: returnPath }}>
            Back to sign in
          </Link>
        </section>
      </main>
    );
  }

  const heading = isLogin ? "Make something extraordinary." : "Start building your ideas.";
  const summary = isLogin
    ? "Sign in to continue building, saving, and exploring your creations."
    : "Create an account to save projects and turn your photos into 3D brick creations.";

  return (
    <section className="auth-layout" aria-labelledby="auth-title">
      <div className="auth-card">
        <div className="auth-card__topbar">
          <Link to="/" className="auth-brand" aria-label="Image to LEGO home">
            <span aria-hidden="true">▦</span>
            Image to <strong>LEGO</strong>
          </Link>
          <Link to="/" className="auth-home-link">← Back to home</Link>
        </div>

        <div className="auth-card__content">
          <p className="eyebrow">{isLogin ? "Welcome back" : "Join the studio"}</p>
          <h1 id="auth-title">{heading}</h1>
          <p className="summary">{summary}</p>

          <div className="oauth-actions" aria-label="Social sign-in options">
            <button className="oauth-button" type="button" onClick={() => void handleOAuth("google")}>Google</button>
            <button className="oauth-button" type="button" onClick={() => void handleOAuth("github")}>GitHub</button>
          </div>
          <div className="auth-divider"><span>{isLogin ? "or continue with email" : "or sign up with email"}</span></div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <label htmlFor="password">Password</label>
            <div className="auth-password-field">
              <input
                id="password"
                type={isPasswordVisible ? "text" : "password"}
                autoComplete={isLogin ? "current-password" : "new-password"}
                placeholder={isLogin ? "Enter your password" : "At least 8 characters"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                type="button"
                className="auth-password-toggle"
                aria-label={isPasswordVisible ? "Hide password" : "Show password"}
                onClick={() => setIsPasswordVisible((visible) => !visible)}
              >
                {isPasswordVisible ? "Hide" : "Show"}
              </button>
            </div>
            {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}
            <button className="button button--yellow" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Please wait…" : isLogin ? "Sign in →" : "Create account →"}
            </button>
          </form>
          <p className="auth-switch">
            {isLogin ? "New here?" : "Already have an account?"}{" "}
            <Link className="text-button" to={isLogin ? "/signup" : "/login"} state={{ returnTo: returnPath }}>
              {isLogin ? "Create an account" : "Sign in"}
            </Link>
          </p>
        </div>
      </div>

      <div className="auth-art" aria-hidden="true">
        <h2>Big ideas<br />start<br />small<span>.</span></h2>
        <img className="auth-art__cat" src="/cat.svg" alt="" />
        <p>From image → to bricks / 2026</p>
      </div>
    </section>
  );
}

function readReturnPath(state: unknown): string | null {
  if (!state || typeof state !== "object" || !("returnTo" in state)) return null;
  const returnTo = state.returnTo;
  return typeof returnTo === "string" ? returnTo : null;
}

function safeReturnPath(path: string | null): string | null {
  if (!path || !path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) return null;
  try {
    const resolvedUrl = new URL(path, window.location.origin);
    return resolvedUrl.origin === window.location.origin ? `${resolvedUrl.pathname}${resolvedUrl.search}${resolvedUrl.hash}` : null;
  } catch {
    return null;
  }
}
