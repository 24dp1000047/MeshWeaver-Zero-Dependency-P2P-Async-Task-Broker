# Requires OpenSSL on PATH.
# Creates a local CA and a node certificate for development/testing only.
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force certs | Out-Null
openssl req -x509 -newkey rsa:2048 -keyout certs/ca.key -out certs/ca.crt -sha256 -days 365 -nodes -subj "/CN=MeshWeaver-Dev-CA"
openssl req -newkey rsa:2048 -keyout certs/node.key -out certs/node.csr -nodes -subj "/CN=localhost"
openssl x509 -req -in certs/node.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial -out certs/node.crt -days 365 -sha256
Remove-Item certs/node.csr, certs/ca.srl -ErrorAction SilentlyContinue
Write-Host "Development certificates created under .\certs"
