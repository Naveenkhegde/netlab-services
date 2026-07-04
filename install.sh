#!/bin/bash
# NetLab Services - Debian/Ubuntu VM Native Installer
set -e

# Colors for output
GREEN='\033[0;32m'
NC='\033[0m'
echo -e "${GREEN}=== NetLab Services Native Installer ===${NC}"

# Check root privilege
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (using sudo)."
  exit 1
fi

# Detect OS
if [ -f /etc/debian_version ]; then
    echo "OS: Debian/Ubuntu detected."
else
    echo "This script is optimized for Debian/Ubuntu based distributions."
    read -p "Do you want to continue anyway? [y/N] " response
    if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        exit 1
    fi
fi

# 1. Install System Dependencies
echo -e "${GREEN}1. Installing system dependencies (dnsmasq, slapd, python3, gcc)...${NC}"
apt-get update
# We pre-seed slapd configuration to avoid interactive prompt
debconf-set-selections <<< "slapd slapd/no_configuration boolean true"
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    dnsmasq \
    slapd \
    ldap-utils \
    wget \
    build-essential \
    bison \
    flex \
    libwrap0-dev \
    libpam0g-dev \
    ufw

# Disable default slapd & dnsmasq service startup (our backend controls them)
echo -e "${GREEN}Disabling default automatic startup of slapd and dnsmasq...${NC}"
systemctl stop dnsmasq || true
systemctl disable dnsmasq || true
systemctl stop slapd || true
systemctl disable slapd || true

# 2. Compile and Install tac_plus
echo -e "${GREEN}2. Compiling Shrubbery tac_plus daemon from source...${NC}"
if [ ! -f /usr/sbin/tac_plus ]; then
    wget http://www.shrubbery.net/pub/tac_plus/tacacs-F4.0.4.28.tar.gz
    tar -xzvf tacacs-F4.0.4.28.tar.gz
    cd tacacs-F4.0.4.28
    ./configure --prefix=/usr --sysconfdir=/etc
    make
    make install
    cd ..
    rm -rf tacacs-F4.0.4.28*
    echo -e "${GREEN}tac_plus installed successfully.${NC}"
else
    echo "tac_plus is already installed."
fi

# 3. Create app directories
echo -e "${GREEN}3. Setting up project files under /opt/netlab-services...${NC}"
INSTALL_DIR="/opt/netlab-services"
mkdir -p "$INSTALL_DIR"
mkdir -p /etc/netlab
mkdir -p /var/lib/ldap
mkdir -p /var/lib/misc

# Copy files
cp -r backend "$INSTALL_DIR/"
cp -r frontend "$INSTALL_DIR/"
cp entrypoint.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/entrypoint.sh"

# 4. Setup Python Virtual Environment
echo -e "${GREEN}4. Setting up Python virtual environment and dependencies...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt"

# 5. Create Systemd Service File
echo -e "${GREEN}5. Creating netlab-services systemd unit...${NC}"
cat > /etc/systemd/system/netlab-services.service <<EOF
[Unit]
Description=NetLab Services Appliance Control Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=NETLAB_DB_PATH=/etc/netlab/netlab.db
ExecStart=$INSTALL_DIR/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 80
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload and enable service
systemctl daemon-reload
systemctl enable netlab-services
systemctl start netlab-services

# 6. Configure Firewall (Optional)
if command -v ufw &> /dev/null; then
    echo -e "${GREEN}6. Configuring firewall rules via UFW...${NC}"
    ufw allow 80/tcp comment "NetLab Control Panel"
    ufw allow 53/udp comment "NetLab DNS"
    ufw allow 53/tcp comment "NetLab DNS"
    ufw allow 67/udp comment "NetLab DHCP"
    ufw allow 389/tcp comment "NetLab LDAP"
    ufw allow 514/udp comment "NetLab Syslog"
    ufw allow 49/tcp comment "NetLab TACACS+"
    ufw allow 1812/udp comment "NetLab RADIUS Auth"
    ufw allow 1813/udp comment "NetLab RADIUS Acct"
fi

echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}NetLab Services Appliance successfully installed!${NC}"
echo -e "You can access the Web interface at: http://$(hostname -I | cut -d' ' -f1)"
echo -e "Manage service state via: systemctl status netlab-services"
echo -e "${GREEN}===========================================${NC}"
EOF
