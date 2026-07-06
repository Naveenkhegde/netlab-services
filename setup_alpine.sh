#!/bin/sh
set -e

echo "=== Alpine VM Chroot Customization Setup ==="

# 1. Enable community repository
echo "Enabling Alpine Community repository..."
grep -v "community" /etc/apk/repositories | sed 's/\/main/\/community/g' >> /etc/apk/repositories
apk update

# 2. Install application packages
echo "Installing application and runtime packages..."
apk add \
    python3 \
    py3-pip \
    dnsmasq \
    openldap \
    openldap-clients \
    openldap-back-mdb \
    chrony \
    wget \
    build-base \
    bison \
    flex \
    libnsl-dev \
    linux-headers \
    bash \
    openrc \
    openssh \
    perl

# 3. Download, compile, and install Shrubbery tac_plus
echo "Downloading and compiling Shrubbery tac_plus..."
wget http://www.shrubbery.net/pub/tac_plus/tacacs-F4.0.4.28.tar.gz
tar -xzvf tacacs-F4.0.4.28.tar.gz
cd tacacs-F4.0.4.28
sed -i '/char.*crypt();/d' tac_pwd.c
./configure CFLAGS="-O2 -std=gnu17" --prefix=/usr --sysconfdir=/etc --without-libwrap
make
make install
cd ..
rm -rf tacacs-F4.0.4.28*

# 4. Create Python Virtual Environment and install packages
echo "Setting up Python virtual environment and backend dependencies..."
python3 -m venv /opt/netlab-services/venv
/opt/netlab-services/venv/bin/pip install --upgrade pip
/opt/netlab-services/venv/bin/pip install -r /opt/netlab-services/backend/requirements.txt

# 5. Enable services in OpenRC runlevels
echo "Configuring service runlevels..."
chown root:root /etc/init.d/netlab-services || true
chmod 755 /etc/init.d/netlab-services || true
chown root:root /etc/network/interfaces || true
chmod 644 /etc/network/interfaces || true
rc-update add loopback boot || true
rc-update add networking boot || true
rc-update add netlab-services default
rc-update add sshd default
rc-update add localdefault default || true

# 6. Configure root login and SSH console access
echo "Configuring root user access..."
echo "root:netlab" | chpasswd
if [ -f /etc/ssh/sshd_config ]; then
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
    echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
fi

# 7. Clean up compilation packages to reduce VM image footprint
echo "Cleaning up compilation build dependencies..."
apk del build-base bison flex linux-headers perl

echo "=== Alpine VM Chroot Customization Complete ==="
exit 0
