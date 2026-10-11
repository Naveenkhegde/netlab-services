# NETLAB-SERVICES(1) Manual Page & Function Reference

## NAME
**netlab-services** — All-in-One Central Network Services & Telemetry Appliance for GNS3, EVE-NG, and Staging Labs

---

## SYNOPSIS
```bash
# Appliance Startup
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 80

# Native Host Installer
sudo ./install.sh

# Alpine Chroot VM Image Builder
sudo ./setup_alpine.sh
```

---

## DESCRIPTION
**NetLab Services** is a high-performance, modular virtual appliance providing DNS, Multi-Scope DHCP, RADIUS AAA with CoA, TACACS+ AAA with granular Command Authorization, OpenLDAP Directory Services, NTP Time Synchronization, TFTP/FTP/Web File Staging, Syslog Logging, and an integrated IPAM (IP Address Management) engine.

This manual documents all functions, methods, API endpoints, parameters, return values, and side effects across every software component of the appliance.

---

## TABLE OF CONTENTS
1. [Backend Database Core (`backend/database.py`)](#1-backend-database-core-backenddatabasepy)
2. [FastAPI Application & API Routers (`backend/main.py`)](#2-fastapi-application--api-routers-backendmainpy)
3. [Service Managers (`backend/services/`)](#3-service-managers-backendservices)
   - [3.1 DNS & DHCP Manager (`dns_dhcp.py`)](#31-dns--dhcp-manager-dns_dhcppy)
   - [3.2 TACACS+ AAA Manager (`tacacs.py`)](#32-tacacs-aaa-manager-tacacspy)
   - [3.3 RADIUS Server & CoA Manager (`radius_server.py`)](#33-radius-server--coa-manager-radius_serverpy)
   - [3.4 OpenLDAP Directory Manager (`ldap.py`)](#34-openldap-directory-manager-ldappy)
   - [3.5 NTP Time Manager (`ntp.py`)](#35-ntp-time-manager-ntppy)
   - [3.6 Syslog Collector & Parser (`syslog_server.py`)](#36-syslog-collector--parser-syslog_serverpy)
   - [3.7 TFTP Storage Manager (`tftp.py`)](#37-tftp-storage-manager-tftppy)
   - [3.8 FTP Storage Manager (`ftp.py`)](#38-ftp-storage-manager-ftppy)
   - [3.9 Network Interface Manager (`network_mgr.py`)](#39-network-interface-manager-network_mgrpy)
   - [3.10 IPAM Engine (`ipam.py`)](#310-ipam-engine-ipampy)
4. [Frontend Single-Page Application (`frontend/js/app.js`)](#4-frontend-single-page-application-frontendjsappjs)
5. [CLI Scripts & Automation Helpers](#5-cli-scripts--automation-helpers)

---

## 1. Backend Database Core (`backend/database.py`)

### `get_db_connection()`
- **Purpose**: Establishes and returns a thread-safe connection to the SQLite database with `sqlite3.Row` factory enabled.
- **Parameters**: None.
- **Returns**: `sqlite3.Connection` instance.
- **Side Effects**: Reads database path from environment variable `NETLAB_DB_PATH` or defaults to `/etc/netlab/netlab.db`.

### `init_db()`
- **Purpose**: Initializes the entire database schema if not present, runs schema migrations, and seeds default web users and network settings.
- **Parameters**: None.
- **Returns**: `None`.
- **Side Effects**:
  - Creates 17 relational tables (`settings`, `dns_records`, `dhcp_static`, `dhcp_ranges`, `interface_configs`, `radius_clients`, `radius_users`, `tacacs_clients`, `tacacs_users`, `tacacs_cmd_rules`, `ldap_users`, `ldap_groups`, `ldap_group_members`, `ipam_subnets`, `ipam_addresses`, `auth_logs`, `web_users`).
  - Seeds default web users: `admin` (hash of `netlab`) and `viewer` (hash of `netlab`).
  - Auto-migrates legacy DHCP configurations and seeds the default management subnet `192.168.1.0/24`.

### `get_setting(key: str, default: Optional[str] = None) -> Optional[str]`
- **Purpose**: Fetches a single configuration parameter from the `settings` table.
- **Parameters**:
  - `key` (*str*): Setting identifier (e.g., `"dns_upstream"`, `"tacacs_secret"`).
  - `default` (*Optional[str]*): Fallback value if key is not found.
- **Returns**: Value string or default.

### `set_setting(key: str, value: Any) -> None`
- **Purpose**: Inserts or updates a configuration key-value pair in the `settings` table.
- **Parameters**:
  - `key` (*str*): Setting identifier.
  - `value` (*Any*): Value to store (automatically converted to `str`).
- **Returns**: `None`.

---

## 2. FastAPI Application & API Routers (`backend/main.py`)

### Lifecycle & Middleware Functions
- **`startup_event()`**: Invoked by FastAPI on startup. Initializes the database, builds initial config files, and launches background daemons (Syslog receiver, TFTP, FTP, RADIUS, and configured system daemons).
- **`shutdown_event()`**: Invoked by FastAPI on graceful shutdown. Closes sockets and terminates all active child daemons.
- **`restart_all_services()`**: Helper that iterates over all service managers and triggers clean restarts after a database restore or JSON configuration import.
- **`verify_admin(x_user_role: str = Header(default="viewer"))`**: Dependency checker verifying that the request caller possesses `admin` rights.
- **`role_authorization_middleware(request: Request, call_next)`**: Intercepts HTTP mutating methods (POST, PUT, DELETE) on mutating endpoints and blocks `viewer` roles with HTTP 403 Forbidden.
- **`get_system_stats()`**: Collects CPU load average, RAM percentage, disk usage, uptime, and active socket listener ports.

### System & Authentication API Endpoints
- **`POST /api/auth/login` (`web_login`)**: Authenticates web dashboard users against `web_users` table using SHA-256 hashed password verification.
- **`GET /api/status` (`get_status`)**: Returns comprehensive telemetry, hardware metrics, and daemon operational states.
- **`POST /api/services/{name}/toggle` (`toggle_service`)**: Starts, stops, or restarts an individual service daemon (`dns`, `dhcp`, `tacacs`, `radius`, `ldap`, `ntp`, `tftp`, `ftp`, `syslog`).

### DNS & DHCP API Endpoints
- **`GET /api/dns` (`get_dns_settings`)**: Retrieves DNS enabled status, upstream forwarders list, and local A/PTR records.
- **`POST /api/dns/settings` (`update_dns_settings`)**: Updates upstream DNS forwarders.
- **`POST /api/dns/records` (`add_dns_record`)**: Creates a local DNS hostname-to-IP mapping.
- **`DELETE /api/dns/records/{hostname}` (`delete_dns_record`)**: Deletes a DNS record by hostname.
- **`GET /api/dhcp` (`get_dhcp_settings`)**: Retrieves DHCP scopes, static leases, global options, and active lease table.
- **`POST /api/dhcp/global-settings` (`update_dhcp_global_settings`)**: Updates global DHCP configuration parameters.
- **`POST /api/dhcp/ranges` (`add_dhcp_range`)**: Adds a new multi-scope DHCP pool (with start/end IP, netmask, gateway, DNS, Option 43 WLC, Option 66 TFTP, Option 42 NTP).
- **`PUT /api/dhcp/ranges/{range_id}` (`update_dhcp_range`)**: Modifies an existing DHCP scope.
- **`DELETE /api/dhcp/ranges/{range_id}` (`delete_dhcp_range`)**: Deletes a DHCP scope by ID.
- **`POST /api/dhcp/static` (`add_dhcp_static`)**: Binds a static MAC address to a fixed IP.
- **`DELETE /api/dhcp/static/{mac_address}` (`delete_dhcp_static`)**: Deletes a static reservation.

### AAA Security API Endpoints (RADIUS, TACACS+, LDAP)
- **`GET /api/radius` (`get_radius_data`)**: Retrieves RADIUS configuration, NAS clients, and user accounts.
- **`POST /api/radius/clients` (`add_radius_client`)**: Registers a NAS client network and shared secret.
- **`DELETE /api/radius/clients/{ip_network}` (`delete_radius_client`)**: Deletes a NAS client.
- **`POST /api/radius/users` (`add_radius_user`)**: Creates a local RADIUS user account.
- **`DELETE /api/radius/users/{username}` (`delete_radius_user`)**: Deletes a RADIUS user account.
- **`POST /api/radius/coa/send` (`send_coa_packet`)**: Injects an RFC 3576 / RFC 5176 CoA or Disconnect-Request packet to a NAS client.
- **`GET /api/tacacs` (`get_tacacs_data`)**: Returns TACACS+ port, secret, NAS clients, users, and privilege levels.
- **`POST /api/tacacs/clients` (`add_tacacs_client`)**: Registers a TACACS+ client NAS.
- **`DELETE /api/tacacs/clients/{ip_network}` (`delete_tacacs_client`)**: Deletes a TACACS+ client.
- **`POST /api/tacacs/users` (`add_tacacs_user`)**: Adds a user with privilege level (1-15) and default action (`permit`/`deny`).
- **`DELETE /api/tacacs/users/{username}` (`delete_tacacs_user`)**: Deletes a TACACS+ user.
- **`GET /api/tacacs/rules` (`get_tacacs_rules`)**: Retrieves command authorization rules.
- **`POST /api/tacacs/rules` (`add_tacacs_rule`)**: Creates a command authorization rule with argument regular expression.
- **`DELETE /api/tacacs/rules/{rule_id}` (`delete_tacacs_rule`)**: Deletes a command rule.
- **`POST /api/tacacs/test-authorization` (`test_tacacs_authorization`)**: Validates a CLI command string against user authorization rules via the built-in simulator.
- **`GET /api/ldap` (`get_ldap_data`)**: Returns LDAP configuration, users, groups, and membership maps.
- **`POST /api/ldap/users` (`add_ldap_user`)**: Adds an LDAP user with posixAccount attributes.
- **`DELETE /api/ldap/users/{username}` (`delete_ldap_user`)**: Deletes an LDAP user.
- **`POST /api/ldap/groups` (`add_ldap_group`)**: Adds a posixGroup.
- **`DELETE /api/ldap/groups/{group_name}` (`delete_ldap_group`)**: Deletes a group.
- **`POST /api/ldap/groups/{group_name}/members` (`update_ldap_group_members`)**: Updates user memberships for a group.

### NTP, File Storage & Syslog Endpoints
- **`GET /api/ntp` (`get_ntp_status`)**: Returns NTP operational status and upstream peer synchronization stats.
- **`POST /api/ntp/settings` (`update_ntp_settings`)**: Configures upstream NTP server pools.
- **`GET /api/files` (`list_files`)**: Lists all files stored in `/var/lib/netlab/files`.
- **`POST /api/files/upload` (`upload_file`)**: Handles multipart file upload to shared staging directory.
- **`DELETE /api/files/{filename}` (`delete_file`)**: Removes a file from staging storage.
- **`GET /api/files/download/{filename}` (`download_file`)**: Serves file download attachment.
- **`GET /api/files/preview/{filename}` (`preview_file`)**: Returns raw text for configuration file preview.
- **`GET /api/syslog/messages` (`get_syslog_messages`)**: Fetches filtered syslog entries with severity/facility metadata.
- **`POST /api/syslog/clear` (`clear_syslogs`)**: Clears the in-memory syslog ring buffer.
- **`GET /api/logs/auth` (`get_auth_logs`)**: Fetches live authentication audit records.
- **`POST /api/logs/auth/clear` (`clear_auth_logs`)**: Clears the authentication logs table.

### Network Interfaces, IPAM & Backup Endpoints
- **`GET /api/network/interfaces` (`get_network_interfaces`)**: Discovers physical/virtual network adapters and operational states.
- **`POST /api/network/interfaces` (`update_network_interface`)**: Configures static/DHCP IP and admin link state.
- **`GET /api/ipam/subnets` (`get_ipam_subnets`)**: Returns subnets with real-time utilization statistics.
- **`POST /api/ipam/subnets` (`add_ipam_subnet`)**: Adds a new IPv4 CIDR subnet.
- **`DELETE /api/ipam/subnets/{subnet_id}` (`delete_ipam_subnet`)**: Deletes an IPAM subnet.
- **`GET /api/ipam/subnets/{subnet_id}/addresses` (`get_ipam_subnet_addresses`)**: Returns address list for a subnet.
- **`POST /api/ipam/addresses` (`save_ipam_address`)**: Updates or creates an IPAM address entry.
- **`DELETE /api/ipam/addresses/{address_id}` (`delete_ipam_address`)**: Deletes an IP address allocation.
- **`POST /api/ipam/sync` (`sync_ipam_services`)**: Auto-discovers and syncs allocations from DHCP leases and interfaces.
- **`GET /api/ipam/search` (`search_ipam`)**: Performs global search across IPAM addresses and subnets.
- **`GET /api/backup/export` (`export_backup`)**: Exports binary SQLite database snapshot.
- **`POST /api/backup/import` (`import_backup`)**: Restores SQLite database with integrity validation.
- **`GET /api/config/export/json` (`export_config_json`)**: Exports human-readable structured JSON configuration.
- **`POST /api/config/import/json` (`import_config_json`)**: Imports JSON configuration and applies settings across all services.

---

## 3. Service Managers (`backend/services/`)

### 3.1 DNS & DHCP Manager (`dns_dhcp.py`)
```python
class DnsmasqManager:
    def __init__(self, db_path, conf_path="/etc/netlab/dnsmasq.conf", lease_path="/var/lib/misc/dnsmasq.leases")
```
- **`generate_config() -> bool`**: Reads DNS records, DHCP scopes, and static leases from SQLite; compiles `/etc/netlab/dnsmasq.conf`. Automatically converts Option 43 WLC IP addresses into hex notation (e.g. `f1040a000001`). Returns `True` if enabled.
- **`start() -> bool`**: Launches `dnsmasq` process in foreground mode with `--conf-file=/etc/netlab/dnsmasq.conf`.
- **`stop() -> None`**: Gracefully terminates `dnsmasq` subprocess.
- **`is_running() -> bool`**: Checks whether `dnsmasq` process is active via `poll()` and fallback `pgrep`.
- **`get_active_leases() -> List[dict]`**: Parses `/var/lib/misc/dnsmasq.leases` returning timestamp, MAC address, IP address, hostname, and client ID.
- **`wlc_ips_to_hex(ips_str: str) -> str`**: Static helper converting comma-separated IPv4 list into Cisco Option 43 sub-option 0xf1 hex string.

---

### 3.2 TACACS+ AAA Manager (`tacacs.py`)
```python
class TacacsManager:
    def __init__(self, db_path, conf_path="/etc/netlab/tac_plus.conf")
```
- **`generate_config() -> bool`**: Queries TACACS+ clients, users, privilege levels, and command rules; compiles Shrubbery `/etc/netlab/tac_plus.conf`.
- **`test_authorization(username: str, full_command: str) -> dict`**: Evaluates a CLI command string against user privilege rules using Python regular expressions; returns `PERMITTED` or `DENIED` with matched rule details.
- **`start() -> bool`**: Launches `tac_plus` daemon on configured TCP port (default 49).
- **`stop() -> None`**: Terminates `tac_plus` daemon process.
- **`is_running() -> bool`**: Returns operational status of `tac_plus`.

---

### 3.3 RADIUS Server & CoA Manager (`radius_server.py`)
```python
class LabRadiusServer(pyrad.server.Server):
    def __init__(self, db_path, dict_path, host="0.0.0.0", port=1812)
```
- **`refresh_clients() -> None`**: Reloads client NAS IP definitions and shared secrets from SQLite into `self.hosts`.
- **`HandleAuthPacket(pkt) -> None`**: Handles incoming `Access-Request` packets; validates PAP / CHAP credentials; replies with `Access-Accept` or `Access-Reject`; logs event to `auth_logs`.
- **`HandleAcctPacket(pkt) -> None`**: Handles incoming `Accounting-Request` packets; replies with `Accounting-Response`.

```python
class RadiusServerManager:
    def __init__(self, db_path, dict_path, host="0.0.0.0", port=1812)
    def start() -> bool
    def stop() -> None
    def refresh() -> None
```

```python
def send_radius_coa(nas_ip: str, coa_port: int = 3799, secret: str = "radsecret", packet_type: str = "Disconnect-Request", user_name: str = "", calling_station_id: str = "", vlan_id: Optional[int] = None, filter_id: str = "") -> dict
```
- **Purpose**: Generates and transmits RFC 3576 / RFC 5176 RADIUS Change of Authorization (Code 43) or Disconnect-Request (Code 40) packets with MD5 request authenticators.
- **Returns**: Dictionary with `status` (`SUCCESS`, `REJECTED`, `TIMEOUT`, `ERROR`), round-trip time (`rtt_ms`), and response message.

---

### 3.4 OpenLDAP Directory Manager (`ldap.py`)
```python
class LdapManager:
    def __init__(self, db_path, conf_path="/etc/netlab/slapd.conf", db_dir="/var/lib/ldap")
```
- **`generate_config() -> bool`**: Compiles OpenLDAP `/etc/netlab/slapd.conf` including schemas (`core`, `cosine`, `inetorgperson`) and MDB backend storage.
- **`start() -> bool`**: Launches `slapd` daemon and calls `initialize_directory()` to provision the base DN and organization tree.
- **`stop() -> None`**: Terminates `slapd` daemon.
- **`is_running() -> bool`**: Returns boolean running status.
- **`_get_ldap_connection() -> ldap3.Connection`**: Establishes local administrator binding connection to LDAP server.
- **`initialize_directory() -> None`**: Provisions root domain (`dc=netlab,dc=local`), `ou=users`, and `ou=groups`.
- **`sync_local_to_ldap(conn, base_dn) -> None`**: Synchronizes SQLite `ldap_users` and `ldap_groups` entries into OpenLDAP.
- **`add_user(username, password, email, first_name, last_name) -> None`**: Creates an LDAP `inetOrgPerson` and `posixAccount`.
- **`delete_user(username) -> None`**: Removes user DN and purges user from all `posixGroup` memberships.
- **`add_group(group_name, description) -> None`**: Creates a `posixGroup` under `ou=groups`.
- **`delete_group(group_name) -> None`**: Removes a `posixGroup`.
- **`update_group_members(group_name, usernames) -> None`**: Updates `memberUid` attribute list for a group.

---

### 3.5 NTP Time Manager (`ntp.py`)
```python
class NtpManager:
    def __init__(self, db_path, config_path="/etc/chrony/chrony.conf")
```
- **`write_config() -> bool`**: Generates `/etc/chrony/chrony.conf` with configured upstream pools and `local stratum 10` fallback.
- **`start() -> bool`**: Launches `chronyd` daemon.
- **`stop() -> None`**: Stops `chronyd` daemon.
- **`get_stats() -> dict`**: Queries `chronyc tracking` and `chronyc sources` to return current stratum, reference ID, and clock offset.

---

### 3.6 Syslog Collector & Parser (`syslog_server.py`)
```python
class SyslogServer:
    def __init__(self, db_path, host="0.0.0.0", port=514)
```
- **`start() -> bool`**: Binds UDP socket to port 514 and starts asynchronous receiver thread.
- **`stop() -> None`**: Sends loopback shutdown packet and unbinds socket.
- **`_process_message(data: bytes, client_ip: str) -> None`**: Parses RFC 3164 / RFC 5424 PRI codes to extract facility and severity; appends parsed message to thread-safe ring buffer.
- **`get_logs(limit=100, severity=None, search=None, facility=None) -> List[dict]`**: Returns filtered log messages matching query criteria.
- **`clear_logs() -> None`**: Resets the log buffer.

---

### 3.7 TFTP Storage Manager (`tftp.py`)
```python
class TftpManager:
    def __init__(self, db_path, root_dir="/var/lib/netlab/files")
```
- **`start() -> bool`**: Spawns `tftpy.TftpServer` thread listening on UDP port 69 serving `/var/lib/netlab/files`.
- **`stop() -> bool`**: Shuts down TFTP listener thread.

---

### 3.8 FTP Storage Manager (`ftp.py`)
```python
class FtpManager:
    def __init__(self, db_path, root_dir="/var/lib/netlab/files")
```
- **`start() -> bool`**: Spawns `pyftpdlib.servers.FTPServer` thread on TCP port 21 with anonymous and authenticated write permissions.
- **`stop() -> bool`**: Closes all active FTP connections and shuts down server socket.

---

### 3.9 Network Interface Manager (`network_mgr.py`)
```python
class NetworkInterfaceManager:
    def __init__(self, db_path)
```
- **`get_interfaces() -> List[dict]`**: Enumerates system network interfaces via `ip -j addr show` with fallback to `/sys/class/net`; joins current operational state with stored configurations in SQLite.
- **`apply_interface_config(ifname, mode, ip_address, netmask, gateway, dns_servers, is_up=True) -> bool`**: Persists settings to SQLite, updates `/etc/network/interfaces`, and applies live IP addresses via `ip addr` and link state via `ip link set`.

---

### 3.10 IPAM Engine (`ipam.py`)
```python
class IpamManager:
    def __init__(self, db_path)
```
- **`get_subnets() -> List[dict]`**: Returns all managed subnets with computed total IPs, usable IPs, allocated count, available count, and usage percentages.
- **`add_subnet(name, cidr, vlan_id=None, vrf=None, gateway=None, description=None) -> int`**: Validates CIDR block and inserts new subnet record.
- **`delete_subnet(subnet_id: int) -> None`**: Deletes a subnet and cascades deletion to all allocated child addresses.
- **`get_subnet_addresses(subnet_id: int) -> dict`**: Returns all allocated addresses within a subnet.
- **`set_address(subnet_id, ip_address, status, hostname="", mac_address="", description="") -> None`**: Creates or updates an IP allocation entry.
- **`delete_address(address_id: int) -> None`**: Deallocates an address.
- **`sync_from_services(dhcp_static_leases=None, active_dhcp_leases=None, interface_configs=None) -> int`**: Automatically maps active DHCP leases, static reservations, and NIC IP addresses into appropriate subnets; returns total synced count.
- **`search(query: str) -> List[dict]`**: Performs substring search across subnets, hostnames, IP addresses, MAC addresses, and descriptions.

---

## 4. Frontend Single-Page Application (`frontend/js/app.js`)

| Function Name | Description |
| :--- | :--- |
| **`checkAuth()`** | Verifies active session token/role in localStorage; redirects to login modal if unauthenticated. |
| **`handleLogin(e)`** | Submits credentials to `/api/auth/login`, stores user role in localStorage, and updates UI headers. |
| **`logout()`** | Clears session credentials and returns dashboard to login state. |
| **`applyRoleRestrictions()`** | Hides or disables modifying action buttons and inputs when user is in `viewer` mode. |
| **`switchTab(targetId)`** | Manages view panel transitions and triggers corresponding data-fetching routines. |
| **`fetchStatus()`** | Polls `/api/status` to update CPU, RAM, Disk, Uptime widgets, and service status cards. |
| **`toggleService(name)`** | Dispatches POST request to `/api/services/{name}/toggle` to start/stop/restart daemons. |
| **`fetchIpamSubnets()`** | Fetches subnet list, calculates progress bar widths, and renders IPAM summary table. |
| **`saveIpamSubnet(event)`** | Submits new CIDR subnet creation form to `/api/ipam/subnets`. |
| **`syncIpam()`** | Triggers automated cross-service IP discovery sync via `/api/ipam/sync`. |
| **`searchIpam()`** | Filters IPAM records based on user search input. |
| **`fetchDns()` / `saveDnsSettings(e)` / `addDnsRecord(e)` / `deleteDnsRecord(host)`** | Handles DNS records management, A/PTR additions, and upstream forwarders updates. |
| **`fetchDhcp()` / `saveScopeForm(e)` / `deleteDhcpScope(id)` / `addDhcpStatic(e)`** | Manages multi-scope DHCP pools, Option 43 WLC settings, static leases, and active lease table. |
| **`fetchRadius()` / `addRadiusClient(e)` / `addRadiusUser(e)`** | Handles RADIUS client NAS and user account management. |
| **`sendCoaModalSubmit(e)`** | Dispatches RFC 3576 CoA / Disconnect Message packet generator form. |
| **`fetchTacacs()` / `addTacacsRule(e)` / `simulateTacacsAuth(e)`** | Manages TACACS+ users, regex command rules, and interactive command simulator. |
| **`fetchLdap()` / `addLdapUser(e)` / `saveLdapMembers(e)`** | Manages OpenLDAP users, groups, and membership modal bindings. |
| **`fetchNtp()` / `saveNtpSettings(e)`** | Manages NTP upstream server pools and drift tracking views. |
| **`fetchFiles()` / `uploadFiles(e)` / `previewFile(name)` / `deleteFile(name)`** | Handles file staging, drag-and-drop upload, text preview modal, and downloads. |
| **`fetchSyslogs()` / `clearSyslogs()`** | Streams and filters real-time UDP 514 syslog messages with severity badges. |
| **`fetchInterfaces()` / `saveInterfaceConfig(e)`** | Manages network adapter enumeration, IP assignment, and link state toggles. |
| **`exportBackupDb()` / `importBackupDb(e)`** | Handles SQLite database backup download and file upload restore. |
| **`exportConfigJson()` / `importConfigJson(e)`** | Handles declarative JSON configuration export and import. |

---

## 5. CLI Scripts & Automation Helpers

### `setup_alpine.sh`
- **Purpose**: Chroot customization script executed during Alpine Linux VM build.
- **Actions**: Enables Alpine community repository, installs system packages (`dnsmasq`, `openldap`, `chrony`, `build-base`), downloads and compiles Shrubbery `tac_plus` with `-std=gnu17`, sets up the Python virtual environment, configures OpenRC runlevels (`rc-update add netlab-services default`), configures root SSH access, and removes compilation dependencies to minimize image footprint.

### `install.sh`
- **Purpose**: Native installer for Debian / Ubuntu server hosts.
- **Actions**: Validates root permissions, installs prerequisite packages, compiles `tac_plus` from source, copies backend/frontend to `/opt/netlab-services`, creates `netlab-services.service` systemd unit, enables the service, and configures UFW firewall rules for all appliance ports.

### `entrypoint.sh`
- **Purpose**: Container runtime entrypoint script.
- **Actions**: Creates required system directories (`/etc/netlab`, `/var/lib/ldap`, `/var/lib/misc`), initializes filesystem permissions, runs `backend/database.py` to seed schema, and launches Uvicorn on port 80.

---

## AUTHORS
Developed by the **NetLab Services Core Team** for enterprise network engineers, lab architects, and certification candidates.

## SEE ALSO
`dnsmasq(8)`, `tac_plus(8)`, `slapd(8)`, `chronyd(8)`, `pyrad(3)`, `ip(8)`, `ufw(8)`
