interface PublicRuntimeConfig {
  apiBaseUrl?: string;
  supabaseUrl?: string;
  supabasePublishableKey?: string;
}

declare global {
  interface Window {
    __IMAGE_TO_LEGO_CONFIG__?: PublicRuntimeConfig;
  }
}

export const publicRuntimeConfig = window.__IMAGE_TO_LEGO_CONFIG__;
