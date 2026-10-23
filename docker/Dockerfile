FROM alpine:3.22

# Test harness only: CoAP client, HTTP client, MQTT client, the edge CoAP
# server, python3's stdlib HTTP server, tc, iptables, and tshark.
# Official Alpine publishes linux/amd64 and linux/arm64. Do not pin a platform.
# The notebook, Jupyter, pandas, and matplotlib stay on the host.
ENV PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

COPY requirements-harness.txt /tmp/requirements-harness.txt
RUN set -eu \
    && rel=$(cut -d. -f1,2 /etc/alpine-release) \
    && grep -q "/v${rel}/community" /etc/apk/repositories \
        || echo "https://dl-cdn.alpinelinux.org/alpine/v${rel}/community" >> /etc/apk/repositories \
    && pkgs=$(awk 'NF && $1 !~ /^#/ { printf "%s ", $1 }' /tmp/requirements-harness.txt) \
    && apk add --no-cache $pkgs \
    && rm /tmp/requirements-harness.txt \
    && command -v coap-client \
    && command -v curl \
    && command -v mosquitto_pub \
    && command -v mosquitto_sub \
    && command -v tc \
    && command -v iptables \
    && command -v tshark \
    && command -v python3 \
    && date --version | grep -q 'GNU coreutils' \
    && date +%s.%N | grep -Eq '^[0-9]+\.[0-9]+$' \
    && python3 -c 'import http.server,socket' \
    && tshark --version >/dev/null

WORKDIR /opt/lab
COPY coap_server.py /opt/lab/coap_server.py
COPY scripts /opt/lab/scripts
COPY http /opt/lab/http
RUN chmod +x /opt/lab/scripts/*.sh \
    && test "$(wc -c < /opt/lab/http/time)" = "10"
