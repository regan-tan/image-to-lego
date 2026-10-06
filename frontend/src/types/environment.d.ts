/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  readonly VITE_UPLOAD_MAX_IMAGE_SIZE_BYTES?: string;
  readonly VITE_UPLOAD_MAX_PIXEL_COUNT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

