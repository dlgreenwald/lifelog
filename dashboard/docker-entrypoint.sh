#!/bin/sh
# Inject OIDC runtime config into the SPA
envsubst '${OIDC_ISSUER_URL} ${OIDC_CLIENT_ID}' \
  < /usr/share/nginx/html/config.js.template \
  > /usr/share/nginx/html/config.js
rm /usr/share/nginx/html/config.js.template
exec "$@"
