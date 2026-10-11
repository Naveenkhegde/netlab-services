# Product Requirements Document (PRD)

## Project: NetLab Services - All-in-One Network Services Appliance

---

### 1. Document Control & Metadata
- **Project Name**: NetLab Services Appliance
- **Document Version**: 1.0.0
- **Status**: Production / Deployed
- **Target Platform**: GNS3, EVE-NG, Cisco CML, Containerlab, QEMU/KVM, Native Linux (Debian/Ubuntu/Alpine), Docker
- **Target Audience**: Network Engineers, Systems Engineers, Certification Candidates (CCNA, CCNP, CCIE, JNCIA/JNCIS/JNCIP/JNCIE), Lab Architects, Academic Instructors, DevOps & Network Automation Engineers.

---

### 2. Executive Summary & Problem Statement

#### 2.1 The Problem
In standard network engineering simulation environments (such as GNS3, EVE-NG, Cisco Modeling Labs, and physical staging testbeds), network devices (routers, switches, firewalls, wireless controllers) require a multitude of auxiliary infrastructure services to simulate enterprise architectures:
1. **Name Resolution**: DNS servers with custom local forwarding and split-horizon domains.
2. **Dynamic Addressing**: DHCP servers supporting multi-scope options (Option 43 for Cisco WLC AP join, Option 66/150 for TFTP/CallManager, Option 42 for NTP).
3. **Enterprise AAA**: RADIUS (802.1X, PAP, CHAP) and TACACS+ (command authorization levels 1-15, accounting) servers.
4. **Identity & Directory Services**: LDAP / Active Directory servers for firewall and VPN user identity mapping.
5. **Time Synchronization**: Local Stratum 10 NTP servers for PKI, SSL, log correlation, and routing protocols.
6. **File Storage & Firmware Distribution**: TFTP, FTP, and SFTP endpoints for router configuration backup (`copy run tftp:`) and firmware staging.
7. **Telemetry & Monitoring**: Syslog servers for centralized diagnostic log aggregation.

Historically, running these services in a lab required deploying 4 to 8 distinct virtual machines (e.g., Windows Server for AD/DNS/DHCP, Linux VM for FreeRADIUS, Linux VM for TACACS+, separate TFTP/Syslog tools). This approach suffers from:
- **Excessive Resource Consumption**: Consuming 8 GB to 16 GB of host RAM and substantial CPU overhead just for auxiliary services.
- **High Setup Friction**: Hours spent manually installing, configuring, and troubleshooting disparate Linux and Windows services.
- **Complex Management**: No single unified dashboard to inspect leases, AAA audit trails, syslog streams, and address allocations.

#### 2.2 The Solution
**NetLab Services** is an ultra-lightweight, all-in-one virtual appliance that consolidates all core network infrastructure services into a single bootable system (<128MB RAM footprint, <5-second boot time) managed through a modern, glassmorphic Single-Page Web Dashboard and a RESTful API.

---

### 3. User Personas & Core Use Cases

| Persona | Description | Key Objectives & Use Cases |
| :--- | :--- | :--- |
| **Lab Builder / Certification Candidate** | Studying for CCNA, CCNP, CCIE, or Juniper tracks. | Needs immediate plug-and-play DNS, DHCP, TACACS+, and RADIUS without configuring underlying Linux daemons. Drag into GNS3, connect to switch, and start testing. |
| **Enterprise Security Engineer** | Validating firewall policies, AAA authorization, and 802.1X. | Simulates TACACS+ command authorization per user, tests RADIUS Change of Authorization (CoA / Disconnect Messages), and integrates LDAP directory with Cisco ASA / Fortinet firewalls. |
| **Network Automation Engineer** | Developing Python / Ansible / Terraform workflows for netdevs. | Uses the REST API to programmatically provision DHCP scopes, IPAM entries, and DNS records; verifies zero-touch provisioning via DHCP Options 43 and 66. |
| **Academic Instructor / Lab Admin** | Managing classroom environments with dozens of student pods. | Rapidly clones lightweight QCOW2 images to student pods, exports/imports lab topology configuration snapshots via JSON, and monitors lab health via UI. |

---

### 4. Functional Requirements (FR)

#### FR-1: Domain Name System (DNS) Service
- **FR-1.1**: Provide a fast, lightweight DNS resolving server using `dnsmasq`.
- **FR-1.2**: Support custom local DNS A-records (hostname to IPv4 mapping) and PTR records.
- **FR-1.3**: Support configurable upstream DNS forwarders (e.g., `8.8.8.8`, `1.1.1.1`, or lab gateway).
- **FR-1.4**: Allow runtime enabling/disabling of DNS service without affecting other services.
- **FR-1.5**: Support domain lookup prevention for local-only domains (`domain-needed`, `bogus-priv`).

#### FR-2: Dynamic Host Configuration Protocol (DHCP) Service
- **FR-2.1**: Support multi-scope DHCP pools with custom pool names, IP start/end ranges, and subnet masks.
- **FR-2.2**: Provide configurable default gateway, DNS servers, domain search suffix, and lease durations per pool.
- **FR-2.3**: Allow binding DHCP scopes to specific network interfaces (e.g., `eth0`, `eth1`).
- **FR-2.4**: Support static DHCP reservations mapping client MAC addresses to fixed IP addresses and hostnames.
- **FR-2.5**: Support advanced enterprise DHCP Options:
  - **Option 43 (Vendor Specific)**: Cisco Wireless LAN Controller (WLC) AP discovery IP list in hex or IPv4 format.
  - **Option 66 / 150**: TFTP server boot IP / VoIP CallManager server address.
  - **Option 42**: NTP time server distribution.
  - **Custom Options**: Raw DHCP options string syntax for specialized vendor hardware.
- **FR-2.6**: Real-time DHCP lease monitoring displaying active IP allocations, client MAC addresses, lease expiry, and client hostnames.

#### FR-3: RADIUS AAA & Policy Enforcement Service
- **FR-3.1**: Built-in RFC 2865 / 2866 RADIUS server engine supporting PAP and CHAP authentication.
- **FR-3.2**: Manage Network Access Server (NAS) clients with dedicated IP addresses/subnets and per-client shared secrets.
- **FR-3.3**: Manage local RADIUS user credentials (username and password).
- **FR-3.4**: Dynamic RFC 3576 / RFC 5176 Change of Authorization (CoA) & Disconnect Message (DM) packet generator for testing dynamic policy resets and dot1x session drops.
- **FR-3.5**: Maintain an immutable authentication audit log capturing timestamp, client IP, username, auth status (Accepted/Rejected), and error diagnostics.

#### FR-4: TACACS+ Device Administration Service
- **FR-4.1**: Native Shrubbery `tac_plus` daemon integration supporting Cisco, Juniper, and Arista network device AAA.
- **FR-4.2**: Client NAS management with granular shared secrets per IP / subnet mask.
- **FR-4.3**: User accounts with privilege level configuration (Privilege levels 1 to 15).
- **FR-4.4**: Configurable default authorization actions per user (`permit` or `deny`).
- **FR-4.5**: Granular command authorization rules supporting command names and argument regular expressions (`argument_regex`).
- **FR-4.6**: Interactive Web-based Command Authorization Tester/Simulator to validate user commands against privilege rules before deploying to live switches.
- **FR-4.7**: Accounting logging capturing executed switch/router commands to `/var/log/tacacs_acct.log`.

#### FR-5: LDAP Directory Services
- **FR-5.1**: Embedded OpenLDAP (`slapd`) directory server maintaining an enterprise directory tree under `dc=netlab,dc=local`.
- **FR-5.2**: Structural organizational units: `ou=users` (`inetOrgPerson`, `posixAccount`) and `ou=groups` (`posixGroup`).
- **FR-5.3**: User management supporting first name, last name, username (`uid`), password, email, and auto-generated UID/GID numbers.
- **FR-5.4**: Group management supporting custom group creation and membership mapping.
- **FR-5.5**: Automated synchronization between SQLite management database and OpenLDAP MDB directory tree.
- **FR-5.6**: Out-of-the-box compatibility with firewall AAA authentication (Cisco ASA, Palo Alto, Fortinet LDAP server groups).

#### FR-6: Network Time Protocol (NTP) Service
- **FR-6.1**: Local NTP time server daemon using `chrony`.
- **FR-6.2**: Support local stratum 10 fallback mode to serve stable clocks to isolated lab networks without Internet access.
- **FR-6.3**: Configurable upstream NTP server pools (e.g., `pool.ntp.org iburst`).
- **FR-6.4**: Real-time clock tracking, stratum verification, and active client connection monitoring.

#### FR-7: File Storage & Staging Services (TFTP / FTP / Web)
- **FR-7.1**: Unified shared root storage directory (`/var/lib/netlab/files`).
- **FR-7.2**: Asynchronous TFTP server listening on UDP port 69 (`tftpy`).
- **FR-7.3**: Lightweight FTP server listening on TCP port 21 (`pyftpdlib`) with anonymous and authenticated read/write access.
- **FR-7.4**: Web-based File Manager allowing drag-and-drop file upload, file preview (text, configs), download, and deletion.
- **FR-7.5**: Support direct router configuration backups (`copy running-config tftp://<ip>/switch1.cfg`).

#### FR-8: Syslog Collector & Log Analyzer
- **FR-8.1**: Asynchronous UDP port 514 Syslog receiver.
- **FR-8.2**: Parsing RFC 3164 and RFC 5424 syslog packets, extracting timestamp, facility, severity (0-7), source IP, and message payload.
- **FR-8.3**: Visual color-coded severity badges (Emergency, Alert, Critical, Error, Warning, Notice, Info, Debug).
- **FR-8.4**: Real-time auto-refreshing log stream with keyword search, facility filter, and severity level filter.
- **FR-8.5**: Buffer management and log clearing functionality.

#### FR-9: IP Address Management (IPAM)
- **FR-9.1**: Subnet management tracking CIDRs (IPv4), subnet names, VLAN IDs, VRF identifiers, and gateway addresses.
- **FR-9.2**: Visual subnet utilization tracking (total IPs, usable IPs, active allocations, DHCP dynamic, DHCP static, reserved, and percentage progress bar).
- **FR-9.3**: Address lifecycle states: `active`, `dhcp`, `dhcp_static`, `reserved`, `available`.
- **FR-9.4**: Automatic IP discovery and synchronization engine pulling allocations from active DHCP leases, static reservations, and local network interfaces.
- **FR-9.5**: Global IPAM address search across subnets, hostnames, MAC addresses, and descriptions.

#### FR-10: Network Interface Manager
- **FR-10.1**: Dynamic auto-discovery of physical and virtual network adapters (`eth0`, `eth1`, etc.).
- **FR-10.2**: Interface IP configuration: Static IPv4 assignment (IP address, netmask, default gateway, DNS) or DHCP client mode.
- **FR-10.3**: Interface administrative link state control (Toggle UP / DOWN).
- **FR-10.4**: Live MAC address and operational state detection.

#### FR-11: System Health & Hardware Monitoring
- **FR-11.1**: Real-time widgets displaying 1-minute CPU load average, RAM utilization percentage, Disk storage usage, and system uptime.
- **FR-11.2**: Live service process supervisor status indicators (Active/Inactive, PID tracking).
- **FR-11.3**: Active network socket listener audit table.

#### FR-12: Role-Based Access Control (RBAC) & Security
- **FR-12.1**: User roles: `admin` (Full Read/Write, service restart, configuration modification) and `viewer` (Read-Only access to dashboards and logs).
- **FR-12.2**: Password hashing using SHA-256 with constant-time verification.
- **FR-12.3**: Role header enforcement (`X-User-Role`) across all modifying API endpoints.

#### FR-13: Configuration Snapshot, Backup & Migration
- **FR-13.1**: Full SQLite binary database export (`.db`) for exact state backup.
- **FR-13.2**: Database import validation and one-click restore with automated service restart.
- **FR-13.3**: Human-readable JSON configuration export (`netlab_config.json`) for lab versioning, sharing, and Git tracking.
- **FR-13.4**: JSON configuration import with transactional database insertion and daemon reloading.

---

### 5. Non-Functional Requirements (NFR)

#### 5.1 Performance & Footprint
- **Boot Time**: Virtual appliance must reach ready state and serve HTTP in < 5 seconds.
- **Memory Footprint**: Total appliance idle memory consumption must not exceed 128 MB RAM on Alpine Linux.
- **CPU Footprint**: Idle CPU utilization must be < 2% on a single virtual CPU core (vCPU).
- **Disk Footprint**: Prebuilt QCOW2 virtual image size must be < 650 MB.

#### 5.2 Portability & Packaging
- **Multiple Deployment Formats**:
  1. **QEMU QCOW2**: Bootable virtual disk image for GNS3, EVE-NG, CML, and KVM.
  2. **GNS3 Appliance File (`.gns3a`)**: Single-click drag-and-drop import template.
  3. **Docker Container**: Multi-service container with Docker Compose support.
  4. **Native Linux Installer**: Automated bash script (`install.sh`) for bare-metal or existing Debian/Ubuntu VMs.
- **Self-Contained**: Web UI assets (fonts, icons, stylesheets, scripts) must be locally hosted with zero mandatory external internet dependencies during runtime.

#### 5.3 Reliability & Fault Tolerance
- **Independent Process Isolation**: A failure in one service (e.g., LDAP) must not crash or degrade other services (e.g., DNS, DHCP, Web API).
- **Automatic Process Supervision**: Daemons managed via sub-processes must handle restart commands cleanly without socket collisions.
- **Database Consistency**: All write transactions must maintain SQLite ACID properties with foreign key constraints.

#### 5.4 Usability & Aesthetics
- **Design System**: Dark-themed, glassmorphic visual language using modern HSL color tokens, balanced whitespace, and crisp typography.
- **Responsiveness**: Fluid layout adapting cleanly from mobile/tablet viewports to widescreen 4K displays.
- **Real-Time Feedback**: Immediate toast notifications and visual indicators for all service actions, errors, and status updates.

---

### 6. Interface & Port Specifications

| Service | Protocol | Port | Description |
| :--- | :--- | :--- | :--- |
| **Web Control Panel** | TCP | `80` | HTTP REST API & Single Page Application |
| **DNS Service** | UDP / TCP | `53` | Domain Name System resolver & local records |
| **DHCP Service** | UDP | `67` | Dynamic Host Configuration Protocol server |
| **LDAP Directory** | TCP | `389` | OpenLDAP slapd directory query & auth |
| **Syslog Receiver** | UDP | `514` | Syslog message collector |
| **TACACS+ AAA** | TCP | `49` | Shrubbery tac_plus authentication & authorization |
| **RADIUS Auth** | UDP | `1812` | RADIUS Authentication (RFC 2865) |
| **RADIUS Acct** | UDP | `1813` | RADIUS Accounting (RFC 2866) |
| **RADIUS CoA / DM** | UDP | `3799` | Change of Authorization / Disconnect Messages |
| **NTP Service** | UDP | `123` | Network Time Protocol daemon |
| **TFTP Storage** | UDP | `69` | Trivial File Transfer Protocol |
| **FTP Storage** | TCP | `21` | File Transfer Protocol |
| **SSH / Console** | TCP | `22` | Appliance Root Management Console |

---

### 7. Success Metrics & Key Performance Indicators (KPIs)

1. **Deployment Speed**: Time to import and boot the appliance in GNS3 / EVE-NG must be under **60 seconds**.
2. **Resource Efficiency**: Appliance consumes **< 128 MB RAM** on 1 vCPU, allowing 20+ appliances or large topologies to run on standard laptop hardware (16GB RAM).
3. **Zero Configuration Drift**: 100% of service settings persisted in SQLite database and reproducible on reboot.
4. **Service Reliability**: Continuous uptime without memory leaks over 720+ hours of lab operation.
5. **Usability Score**: All core services manageable with zero command-line interaction required for day-to-day lab workflows.
