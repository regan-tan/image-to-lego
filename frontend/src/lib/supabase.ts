import { createClient } from "@supabase/supabase-js";
import { publicRuntimeConfig } from "../runtimeConfig";

const supabaseUrl = publicRuntimeConfig?.supabaseUrl ?? import.meta.env.VITE_SUPABASE_URL;
const supabasePublishableKey =
  publicRuntimeConfig?.supabasePublishableKey ?? import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

export const supabase = supabaseUrl && supabasePublishableKey
  ? createClient(supabaseUrl, supabasePublishableKey)
  : null;

export const isSupabaseConfigured = supabase !== null;
