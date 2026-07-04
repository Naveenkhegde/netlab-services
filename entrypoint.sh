#!/bin/bash
set -e

echo "Starting NetLab Services Appliance..."

# Create necessary directories
mkdir -p /etc/netlab
mkdir -p /var/lib/ldap
mkdir -p /var/lib/misc
mkdir -p /var/run

# Initialize directory permissions
chown -R openldap:openldap /var/lib/ldap || true
touch /var/lib/misc/dnsmasq.leases || true

# Initialize database
python3 /app/backend/database.py

# Start FastAPI application
# We listen on 0.0.0.0:80 to serve the Web UI and API
exec uvicorn backend.main:app --host 0.0.0.0 --port 80
