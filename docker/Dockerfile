FROM debian:bookworm-slim

# One image for the device, the edge, the application, and the capture
# sidecar. Official Debian publishes amd64 and arm64, so the same file
# builds on Linux and on Docker Desktop for Apple Silicon.
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

RUN apt-get update \
    && echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections \
    && apt-get install -y --no-install-recommends \
        bc \
        ca-certificates \
        curl \
        iproute2 \
        iptables \
        iputils-ping \
        libcoap3-bin \
        mosquitto-clients \
        procps \
        python3 \
        tshark \
    && ln -sf /usr/bin/coap-client-openssl /usr/local/bin/coap-client \
    && ln -sf /usr/bin/coap-server-openssl /usr/local/bin/coap-server \
    && command -v coap-client \
    && command -v curl \
    && command -v mosquitto_pub \
    && command -v mosquitto_sub \
    && command -v tc \
    && command -v tshark \
    && command -v pgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lab
COPY docker/coap_server.py /opt/lab/coap_server.py
COPY docker/scripts /opt/lab/scripts
COPY docker/http /opt/lab/http
RUN chmod +x /opt/lab/scripts/*.sh \
    && test "$(wc -c < /opt/lab/http/time)" = "10"
