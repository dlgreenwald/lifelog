import { UserManagerSettings, WebStorageStateStore } from 'oidc-client-ts';

interface OidcWindowConfig {
  authority: string;
  clientId: string;
}

declare global {
  interface Window {
    __OIDC_CONFIG__?: OidcWindowConfig;
  }
}

export function getOidcConfig(): UserManagerSettings {
  const cfg = window.__OIDC_CONFIG__;
  return {
    authority: cfg?.authority ?? '',
    client_id: cfg?.clientId ?? '',
    redirect_uri: `${window.location.origin}/callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code',
    scope: 'openid profile offline_access',
    automaticSilentRenew: false,
    userStore: new WebStorageStateStore({ store: localStorage }),
  };
}
