import type { Session } from "@supabase/supabase-js";
import { useOutletContext } from "react-router-dom";

export interface AppLayoutContext {
  session: Session;
  openNewProject: () => void;
  openHowItWorks: () => void;
}

/** Signed-in pages read the session and shared dialog openers from the app layout. */
export function useAppLayout(): AppLayoutContext {
  return useOutletContext<AppLayoutContext>();
}
