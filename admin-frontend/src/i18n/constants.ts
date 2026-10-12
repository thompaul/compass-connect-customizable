import { getDefaultLocale } from "src/envService";

// Default locale, now loaded from environment variable FRONTEND_DEFAULT_LOCALE (base64-encoded in env.js)
export const DEFAULT_LOCALE = getDefaultLocale();

export enum Locale {
  EN_GB = "en-GB",
  EN_US = "en-US",
  ES_ES = "es-ES",
  ES_AR = "es-AR",
  SW_KE = "sw-KE",
  NY_ZM = "ny-ZM",
  PT_MZ = "pt-MZ",
}

export const LocalesLabels = {
  [Locale.EN_GB]: "English (UK)",
  [Locale.EN_US]: "English (US)",
  [Locale.ES_ES]: "Español (España)",
  [Locale.ES_AR]: "Español (Argentina)",
  [Locale.SW_KE]: "Kiswahili (Kenya)",
  [Locale.NY_ZM]: "Nyanja (Zambia)",
  [Locale.PT_MZ]: "Portuguese (Mozambique)",
} as const;

/**
 * The locales a deployment may choose from.
 *
 * This is the *product's* list, not a deployment's — `parseEnvSupportedLocales` filters the
 * deployment's own choice against it. Every entry here must also be one the backend can hold
 * a conversation in: a locale offered on one side only is selectable in the interface and
 * broken in the agent, which is how `ny-ZM` came to be documented in the runbook as a locale
 * to avoid rather than removed from the menu.
 *
 * `Locale`, `LocalesLabels` and the translation files above keep their `ny-ZM` entries, so
 * adding it back is one line here once the backend supports it. `iac/test_locales.py` is the
 * gate that keeps the three tiers in step.
 */
export const SupportedLocales: Locale[] = [
  Locale.EN_GB,
  Locale.EN_US,
  Locale.ES_ES,
  Locale.ES_AR,
  Locale.SW_KE,
  Locale.PT_MZ,
];
export const FALL_BACK_LOCALE = Locale.EN_GB;
