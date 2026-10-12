import { getAppIconUrl, getChatAvatarUrl, getDarkLogoUrl, getFaviconUrl, getLogoUrl } from "src/envService";

/**
 * The assets a deployment falls back to when it has not supplied its own.
 *
 * These are Compass Connect's own marks. They carry no partner identity, which is the
 * point: an unconfigured deployment must not present itself as some other organisation.
 * Every one of these files ships in `public/`, so a fallback never depends on the network.
 */
export const DEFAULT_BRAND_ASSETS = {
  LOGO_LIGHT: "/compass-connect-logo-light.svg",
  LOGO_DARK: "/compass-connect-logo-dark.svg",
  FAVICON: "/compass-connect-favicon.svg",
  APP_ICON: "/compass-connect-favicon.svg",
  CHAT_AVATAR: "/compass-connect-chat-avatar.svg",
};

const withPublicUrl = (path: string) => `${process.env.PUBLIC_URL}${path}`;

/**
 * The logo to show against a light background.
 *
 * A deployment that configures only one of the two logo variants gets that one in both
 * places, which is better than showing it a Compass Connect mark next to its own name.
 */
export const resolveDarkLogoUrl = (): string =>
  getDarkLogoUrl() || getLogoUrl() || withPublicUrl(DEFAULT_BRAND_ASSETS.LOGO_DARK);

/** The logo to show against a dark background, with the same one-variant-is-enough rule. */
export const resolveLightLogoUrl = (): string =>
  getLogoUrl() || getDarkLogoUrl() || withPublicUrl(DEFAULT_BRAND_ASSETS.LOGO_LIGHT);

export const resolveFaviconUrl = (): string => getFaviconUrl() || withPublicUrl(DEFAULT_BRAND_ASSETS.FAVICON);

export const resolveAppIconUrl = (): string => getAppIconUrl() || withPublicUrl(DEFAULT_BRAND_ASSETS.APP_ICON);

export const resolveChatAvatarUrl = (): string => getChatAvatarUrl() || withPublicUrl(DEFAULT_BRAND_ASSETS.CHAT_AVATAR);
