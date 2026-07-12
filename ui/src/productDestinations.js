// Mirrors src/dictate/pro/product_destinations.py — keep URLs in sync.
export const ACCOUNT_PORTAL_BASE_URL = "https://deck.arcforge.au/dictate";
export const ACCOUNT_LOGIN_URL = "https://deck.arcforge.au/account/login";

export const PRODUCT_DESTINATIONS = {
  hub: ACCOUNT_PORTAL_BASE_URL,
  plan: `${ACCOUNT_PORTAL_BASE_URL}/plan`,
  usage: `${ACCOUNT_PORTAL_BASE_URL}/usage`,
  billing: `${ACCOUNT_PORTAL_BASE_URL}/billing`,
  devices: `${ACCOUNT_PORTAL_BASE_URL}/devices`,
  sync_recovery: `${ACCOUNT_PORTAL_BASE_URL}/sync-recovery`,
};
