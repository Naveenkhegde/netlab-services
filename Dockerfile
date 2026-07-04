FROM debian:bookworm-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV NETLAB_DB_PATH=/etc/netlab/netlab.db

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    dnsmasq \
    slapd \
    ldap-utils \
    wget \
    build-essential \
    bison \
    flex \
    libwrap0-dev \
    libpam0g-dev \
    && rm -rf /var/lib/apt/lists/*

# Download, compile, and install Shrubbery tac_plus
RUN wget http://www.shrubbery.net/pub/tac_plus/tacacs-F4.0.4.28.tar.gz && \
    tar -xzvf tacacs-F4.0.4.28.tar.gz && \
    cd tacacs-F4.0.4.28 && \
    ./configure --prefix=/usr --sysconfdir=/etc && \
    make && \
    make install && \
    cd .. && \
    rm -rf tacacs-F4.0.4.28*

# Setup working directory
WORKDIR /app

# Copy requirements and install python packages
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/backend/requirements.txt

# Copy source code and entrypoint
COPY backend /app/backend
COPY frontend /app/frontend
COPY entrypoint.sh /app/entrypoint.sh

# Expose service ports
# 80: HTTP (Web Panel)
# 53: DNS (UDP/TCP)
# 67: DHCP (UDP)
# 389: LDAP (TCP)
# 514: Syslog (UDP)
# 49: TACACS+ (TCP)
# 1812: RADIUS Auth (UDP)
# 1813: RADIUS Acct (UDP)
EXPOSE 80 53/udp 53/tcp 67/udp 389 514/udp 49 1812/udp 1813/udp

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
