import type { Session } from "@supabase/supabase-js";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { supabase } from "../lib/supabase";

export type AuthenticationMode = "login" | "signup";

interface AuthenticationFormProps {
  mode: AuthenticationMode;
  onAuthenticated: (session: Session) => void;
}

export function AuthenticationForm({ mode, onAuthenticated }: AuthenticationFormProps) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const isLogin = mode === "login";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const client = supabase;
    if (!client) {
      return;
    }

    setErrorMessage(null);
    setIsSubmitting(true);
    try {
      if (!isLogin) {
        const { data, error } = await client.auth.signUp({ email, password });
        if (error) {
          setErrorMessage("We could not create your account. Check your details and try again.");
        } else if (data.session) {
          onAuthenticated(data.session);
          navigate("/");
        } else {
          setPassword("");
          setShowConfirmation(true);
        }
        return;
      }

      const { data, error } = await client.auth.signInWithPassword({ email, password });
      if (error || !data.session) {
        setErrorMessage("We could not sign you in. Check your email and password and try again.");
        return;
      }
      onAuthenticated(data.session);
      navigate("/");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleOAuth(provider: "google" | "github") {
    const client = supabase;
    if (!client) {
      return;
    }

    setErrorMessage(null);
    const { error } = await client.auth.signInWithOAuth({
      provider,
      options: { redirectTo: new URL("/", window.location.origin).toString() },
    });
    if (error) {
      setErrorMessage("We could not start sign-in. Please try again.");
    }
  }

  if (showConfirmation) {
    return (
      <section className="auth-card" aria-labelledby="confirmation-title">
        <p className="eyebrow">One more step</p>
        <h2 id="confirmation-title">Check your email</h2>
        <p className="summary">
          We sent a confirmation link to {email}. Confirm your address, then sign in to continue.
        </p>
        <button
          className="button"
          type="button"
          onClick={() => {
            setPassword("");
            navigate("/login");
          }}
        >
          Back to sign in
        </button>
      </section>
    );
  }

  const heading = isLogin ? "Sign in" : "Create your account";
  const submitLabel = isLogin ? "Sign in" : "Sign up";

  return (
    <section className="auth-card" aria-labelledby="auth-title">
      <p className="eyebrow">Image to LEGO</p>
      <h1 id="auth-title">{heading}</h1>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete={isLogin ? "current-password" : "new-password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        {errorMessage ? <p className="form-error" role="alert">{errorMessage}</p> : null}
        <button className="button" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Please wait…" : submitLabel}
        </button>
      </form>
      <p className="auth-switch">
        {isLogin ? "New to Image to LEGO?" : "Already have an account?"}{" "}
        <Link className="text-button" to={isLogin ? "/signup" : "/login"}>
          {isLogin ? "Sign up" : "Sign in"}
        </Link>
      </p>
      <div className="oauth-actions" aria-label="Social sign-in options">
        <button className="oauth-button" type="button" onClick={() => void handleOAuth("google")}>
          Continue with Google
        </button>
        <button className="oauth-button" type="button" onClick={() => void handleOAuth("github")}>
          Continue with GitHub
        </button>
      </div>
    </section>
  );
}
