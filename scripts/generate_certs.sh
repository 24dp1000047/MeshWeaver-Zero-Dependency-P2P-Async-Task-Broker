#!/usr/bin/env bash
set -euo pipefail
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -keyout certs/ca.key -out certs/ca.crt -sha256 -days 365 -nodes -subj "/CN=MeshWeaver-Dev-CA"
openssl req -newkey rsa:2048 -keyout certs/node.key -out certs/node.csr -nodes -subj "/CN=localhost"
openssl x509 -req -in certs/node.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial -out certs/node.crt -days 365 -sha256
rm -f certs/node.csr certs/ca.srl
echo "Development certificates created under ./certs"
