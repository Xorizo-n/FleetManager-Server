#!/bin/sh
# Временный самоподписанный сертификат для HTTPS, пока нет сертификата от УЦ.
# Существующие fleet.crt и fleet.key не трогает: настоящий сертификат кладётся
# в тот же каталог (том ./certs) под этими же именами.
set -eu

dir=/etc/nginx/certs
crt="$dir/fleet.crt"
key="$dir/fleet.key"

if [ -s "$crt" ] && [ -s "$key" ]; then
    exit 0
fi

mkdir -p "$dir"
san="${TLS_SELF_SIGNED_SAN:-DNS:localhost}"
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -subj "/CN=Fleet Manager (self-signed)" \
    -addext "subjectAltName=$san" \
    -keyout "$key" -out "$crt" 2>/dev/null
chmod 600 "$key"
echo "40-fleet-tls.sh: generated a self-signed certificate for $san"
