#!/bin/sh
# Inject OIDC runtime config into the SPA
envsubst '${OIDC_ISSUER_URL} ${OIDC_CLIENT_ID}' \
  < /usr/share/nginx/html/config.js.template \
  > /usr/share/nginx/html/config.js
rm /usr/share/nginx/html/config.js.template

# Derive CSP connect-src origin from OIDC issuer URL (scheme + host only)
if [ -n "$OIDC_ISSUER_URL" ]; then
  OIDC_CSP_CONNECT_SRC=$(echo "$OIDC_ISSUER_URL" | sed 's|^\([^:]*://[^/]*\).*|\1|')
else
  OIDC_CSP_CONNECT_SRC="'none'"
fi
export OIDC_CSP_CONNECT_SRC

# Inject env vars into nginx config
envsubst '${OIDC_CSP_CONNECT_SRC}' \
  < /etc/nginx/conf.d/default.conf \
  > /etc/nginx/conf.d/default.conf.tmp
mv /etc/nginx/conf.d/default.conf.tmp /etc/nginx/conf.d/default.conf

exec "$@"
