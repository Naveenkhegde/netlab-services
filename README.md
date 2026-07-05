# NetLab Services - All-in-One Network Services Appliance

**NetLab Services** is a centralized, lightweight services appliance designed specifically for network engineering topologies (such as GNS3, EVE-NG, or physical labs). It packages key network services (DNS, DHCP, RADIUS, TACACS+, LDAP, and Syslog) into a single instance managed via an elegant, glassmorphic Web UI.

Rather than running multiple VMs or complex configurations, this project provides a bootable, lightweight **QEMU virtual disk image (`.qcow2`)** based on Alpine Linux that boots in under 5 seconds and consumes less than 128MB of RAM.

---

## Features
- 🌐 **DNS Server (`dnsmasq`)**: Local A-records, domain mappings, and upstream forwarding.
- 📶 **DHCP Server (`dnsmasq`)**: Dynamic IP pools, gateway/DNS option distributions, and static IP-MAC reservations.
- 🔐 **RADIUS Server (`pyrad`)**: PAP/CHAP AAA client (NAS) authentication and user account management.
- 🛡️ **TACACS+ Server (`tac_plus`)**: Cisco/Juniper management authentication, authorization, and accounting with customizable privilege levels (1-15).
- 📂 **LDAP Server (OpenLDAP `slapd`)**: Centralized directory structure simulation (under `ou=users` and `ou=groups`) for enterprise AAA setups.
- ⏰ **NTP Server (`chrony`)**: Time synchronization daemon serving clocks to lab devices (supports local stratum 10 fallback).
- 📁 **File Store (TFTP / FTP / SFTP)**: Direct configuration upload/download support from routers and switches to a central shared directory (`/var/lib/netlab/files`).
- 📊 **Syslog Collector**: Real-time UDP port 514 syslog server displaying logs color-coded by facility/severity with instant filtering.
- 💻 **Hardware Monitoring**: Instant widgets showing CPU load, RAM usage, disk usage, and uptime.

---

## Project Output Files
- `netlab-services.qcow2`: The prebuilt, bootable Alpine Linux QEMU disk image (616MB).
- `netlab-services.gns3a`: Official GNS3 appliance template for one-click drag-and-drop integration.
- `install.sh`: Native bash script to deploy on a clean Debian/Ubuntu VM.
- `/backend`: FastAPI Python server and SQLite configuration database.
- `/frontend`: Responsive Single-Page Application (HTML5 / Vanilla CSS / Vanilla JS) with dark theme and glassmorphic dashboards.

---

## Deployment Options

### Option 1: Importing into GNS3 (Recommended)
Deploying NetLab Services as a QEMU virtual machine in GNS3 is extremely resource-efficient:

1. Copy the pre-built `netlab-services.qcow2` image to your GNS3 server's images directory (or let GNS3 upload it during import).
2. Open GNS3 and go to **File > Import Appliance**.
3. Select the provided `netlab-services.gns3a` template file.
4. GNS3 will add the appliance to your **End Devices** list.
5. Drag the **NetLab Services** node into your topology and connect `eth0` to your lab switch.
6. Start the node. It will request an IP via DHCP on boot and display boot progress on the telnet console.
7. Open a browser on your management PC and navigate to `http://<appliance-ip>` to access the Web UI.

### Option 2: Native VM Installation (Ubuntu / Debian Server)
If you have a dedicated virtual machine (QEMU/KVM/ESXi) running Ubuntu/Debian:
1. Copy or clone this codebase onto the VM.
2. Make the installer executable and run as root:
   ```bash
   sudo chmod +x install.sh
   sudo ./install.sh
   ```
3. The installer compiles `tac_plus` from source, configures OpenLDAP, sets up a systemd daemon (`netlab-services.service`), configures the local UFW firewall, and boots the control panel on port 80.

---

## Default Configurations & Credentials
- **Web Console Login**:
  - **Admin (Read/Write)**: `admin` / `netlab`
  - **Viewer (Read Only)**: `viewer` / `netlab`
- **VM Serial Console / SSH Access**: Root user: `root` (Password: `netlab`)
- **RADIUS Secret**: Defaults to `radsecret` (configurable in the UI per client/subnet)
- **TACACS+ Secret**: Defaults to `tacsecret` (configurable in the UI per client/subnet)
- **LDAP Base DN**: `dc=netlab,dc=local`
- **LDAP Root Manager DN**: `cn=admin,dc=netlab,dc=local` (Password: `adminpassword`)

---

## Example Network Client Configurations

### Cisco IOS (TACACS+ AAA Admin Access)
```cisco
! Define TACACS+ server
tacacs-server host <appliance-ip> key tacsecret

! Configure Authentication & Authorization
aaa new-model
aaa authentication login default group tacacs+ local
aaa authorization exec default group tacacs+ local
aaa accounting exec default start-stop group tacacs+
```

### Cisco IOS (RADIUS Network Authentication / Dot1x)
```cisco
! Define RADIUS server
radius-server host <appliance-ip> auth-port 1812 acct-port 1813 key radsecret

! Configure Dot1x AAA
aaa new-model
aaa authentication dot1x default group radius
```

### Cisco ASA Firewall (LDAP Authentication)
```cisco
! Configure LDAP Server Group
ldap-server-group LDAP-Group
ldap-server-group (inside) LDAP-Group
server-active LDAP-Server

! Define LDAP Server Params
ldap-server LDAP-Server host <appliance-ip>
 server-port 389
 ldap-base-dn ou=users,dc=netlab,dc=local
 ldap-login-dn cn=admin,dc=netlab,dc=local
 ldap-login-password adminpassword
 ldap-scope subtree
```

---

## License
MIT License. Created for lab and training simulation environments.
