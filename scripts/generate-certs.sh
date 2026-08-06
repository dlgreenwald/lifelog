#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Generating CA certificate..."

# Generate CA certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ca.key -out ca.crt \
  -subj "/CN=LifeLog CA" 2>/dev/null

echo "Generating server certificates for each service..."

# Generate server certificate for each service
for service in server diarization speaker-id; do
  mkdir -p "$service/certs"

  # Generate private key
  openssl genrsa -out "$service/certs/server.key" 2048 2>/dev/null

  # Generate CSR
  openssl req -new -key "$service/certs/server.key" \
    -out "$service/certs/server.csr" \
    -subj "/CN=$service.lifelog.local" 2>/dev/null

  # Sign with CA
  openssl x509 -req -days 365 \
    -in "$service/certs/server.csr" \
    -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$service/certs/server.crt" 2>/dev/null

  # Copy CA cert
  cp ca.crt "$service/certs/"

  # Clean up CSR
  rm -f "$service/certs/server.csr"

  echo "  ✓ $service certificates generated"
done

# Copy CA cert to server for service verification
cp ca.crt server/certs/

echo ""
echo "Certificates generated successfully!"
echo ""
echo "Files created:"
echo "  ca.key / ca.crt                         (CA root)"
echo "  server/certs/server.{key,crt}           (orchestrator)"
echo "  diarization/certs/server.{key,crt}      (diarization)"
echo "  speaker-id/certs/server.{key,crt}       (speaker-id)"
