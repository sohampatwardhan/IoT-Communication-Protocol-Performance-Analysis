# eclipse-mosquitto:2 is Alpine. Its 2.1 clients replace Alpine's 2.0
# mosquitto-clients package. See requirements-harness.txt.
FROM eclipse-mosquitto:2 AS mqttcli

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
    && command -v tc \
    && command -v iptables \
    && command -v tshark \
    && command -v python3 \
    && date --version | grep -q 'GNU coreutils' \
    && date +%s.%N | grep -Eq '^[0-9]+\.[0-9]+$' \
    && python3 -c 'import http.server,socket' \
    && tshark --version >/dev/null

COPY --from=mqttcli /usr/bin/mosquitto_pub /usr/bin/mosquitto_pub
COPY --from=mqttcli /usr/bin/mosquitto_sub /usr/bin/mosquitto_sub
COPY --from=mqttcli /usr/lib/libmosquitto.so.1 /usr/lib/libmosquitto.so.1
COPY --from=mqttcli /usr/lib/libcjson.so.1 /usr/lib/libcjson.so.1
RUN mosquitto_pub 2>&1 | grep -q 'version 2.1' \
    && mosquitto_sub 2>&1 | grep -q 'version 2.1' \
    && ldd /usr/bin/mosquitto_pub

WORKDIR /opt/lab
COPY coap_server.py /opt/lab/coap_server.py
COPY scripts /opt/lab/scripts
COPY http /opt/lab/http
RUN chmod +x /opt/lab/scripts/*.sh \
    && test "$(wc -c < /opt/lab/http/time)" = "10"
