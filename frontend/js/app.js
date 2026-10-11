// Intercept global fetch to automatically add X-User-Role header for all API calls
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    if (url.toString().startsWith("/api/")) {
        options.headers = options.headers || {};
        options.headers["X-User-Role"] = sessionStorage.getItem("role") || "viewer";
    }
    return originalFetch(url, options);
};

// Safe response error parser (handles JSON, text, and HTML error pages gracefully)
async function parseResponseError(res, defaultMsg = "Request failed") {
    try {
        const text = await res.text();
        if (text) {
            try {
                const data = JSON.parse(text);
                return data.detail || data.message || defaultMsg;
            } catch (e) {
                const cleaned = text.replace(/<[^>]*>?/gm, ' ').replace(/\s+/g, ' ').trim();
                return cleaned.substring(0, 150) || res.statusText || defaultMsg;
            }
        }
    } catch (e) {
        // Fallback
    }
    return res.statusText || defaultMsg;
}

let currentGroupForMembers = null;

document.addEventListener("DOMContentLoaded", () => {
    // Check Auth Session
    const authenticated = checkAuth();

    // 1. Setup Navigation Toggles
    const menuLinks = document.querySelectorAll(".menu-link");
    menuLinks.forEach(link => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            const targetId = link.getAttribute("data-target");
            switchTab(targetId);
        });
    });

    if (authenticated) {
        // 2. Initial Data Load & Periodic Refresh
        fetchStatus();
        fetchSyslogs();
    }
    
    // Interval for hardware stats & service states
    setInterval(() => {
        if (sessionStorage.getItem("username")) fetchStatus();
    }, 3000);
});

// --- Auth Handling & Role Restrictions ---
function checkAuth() {
    const username = sessionStorage.getItem("username");
    const role = sessionStorage.getItem("role");
    
    const overlay = document.getElementById("login-overlay");
    if (!username || !role) {
        overlay.style.display = "flex";
        return false;
    } else {
        overlay.style.display = "none";
        
        // Update user & role labels in sidebar
        document.getElementById("sb-user").textContent = username;
        document.getElementById("sb-role").textContent = role;
        
        // Show role badge
        const badge = document.getElementById("role-badge");
        badge.style.display = "inline-flex";
        if (role === "admin") {
            badge.style.background = "rgba(16, 185, 129, 0.1)";
            badge.style.color = "var(--success)";
            badge.style.borderColor = "rgba(16, 185, 129, 0.2)";
            badge.innerHTML = "Admin (Read/Write)";
        } else {
            badge.style.background = "rgba(245, 158, 11, 0.1)";
            badge.style.color = "var(--warning)";
            badge.style.borderColor = "rgba(245, 158, 11, 0.2)";
            badge.innerHTML = "Viewer (Read-Only)";
        }
        applyRoleRestrictions();
        return true;
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value.trim();
    const errorEl = document.getElementById("login-error");
    
    errorEl.style.display = "none";
    
    try {
        const response = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });
        
        if (!response.ok) {
            throw new Error("Invalid username or password");
        }
        
        const data = await response.json();
        sessionStorage.setItem("username", data.username);
        sessionStorage.setItem("role", data.role);
        
        // Clean fields
        document.getElementById("login-username").value = "";
        document.getElementById("login-password").value = "";
        
        checkAuth();
        
        // Trigger initial data load
        fetchStatus();
        fetchSyslogs();
        
    } catch (err) {
        errorEl.style.display = "block";
    }
}

function logout() {
    sessionStorage.clear();
    location.reload();
}

function applyRoleRestrictions() {
    const role = sessionStorage.getItem("role");
    const isViewer = role === "viewer";
    
    // Disable all switch toggles
    document.querySelectorAll(".switch input").forEach(input => {
        input.disabled = isViewer;
    });
    
    // Disable all submit buttons/forms
    document.querySelectorAll("form button, form input[type='submit'], .btn-primary").forEach(btn => {
        // Do not disable the login form submit button!
        if (btn.closest("#login-form")) return;
        btn.disabled = isViewer;
        if (isViewer) {
            btn.style.opacity = "0.5";
            btn.style.cursor = "not-allowed";
        } else {
            btn.style.opacity = "1";
            btn.style.cursor = "pointer";
        }
    });
    
    // Hide delete buttons in tables
    document.querySelectorAll("table .btn-danger, table button[onclick*='delete'], table button[onclick*='clear']").forEach(btn => {
        btn.disabled = isViewer;
        if (isViewer) {
            btn.style.display = "none";
        } else {
            btn.style.display = "inline-flex";
        }
    });
    
    // Hide edit/actions columns or buttons
    document.querySelectorAll(".btn-secondary.btn-sm").forEach(btn => {
        if (btn.textContent.toLowerCase().includes("members")) {
            btn.disabled = isViewer;
            if (isViewer) {
                btn.style.display = "none";
            } else {
                btn.style.display = "inline-flex";
            }
        }
    });
}

// --- Tab Switching ---
function switchTab(targetId) {
    // Update active class on menu link
    document.querySelectorAll(".menu-link").forEach(l => {
        if (l.getAttribute("data-target") === targetId) {
            l.classList.add("active");
        } else {
            l.classList.remove("active");
        }
    });

    // Update active class on view panels
    document.querySelectorAll(".view-panel").forEach(panel => {
        if (panel.id === targetId) {
            panel.classList.add("active");
        } else {
            panel.classList.remove("active");
        }
    });

    // Update headers
    const titleMap = {
        "view-dashboard": { t: "Services Dashboard", s: "Centralized network services panel for GNS3" },
        "view-ipam": { t: "IP Address Manager (IPAM)", s: "Centralized IPv4 subnet tracking and address allocation management" },
        "view-dns": { t: "Local DNS Settings", s: "Name resolution configuration and forwarding rules" },
        "view-dhcp": { t: "DHCP Server Pools", s: "Subnet scope configs and address reservations" },
        "view-radius": { t: "RADIUS Authentication", s: "Remote AAA authentication configuration" },
        "view-tacacs": { t: "TACACS+ Administration", s: "Command authorization and management access control" },
        "view-ldap": { t: "LDAP Directory Tree", s: "Centralized network directory management" },
        "view-ntp": { t: "NTP Time Synchronization", s: "Network Time Protocol daemon management" },
        "view-files": { t: "Shared File Manager", s: "Upload and download configurations via TFTP, FTP, and SFTP" },
        "view-interfaces": { t: "Network Interfaces", s: "System ethernet interfaces and IP address settings" },
        "view-backup": { t: "Configuration & Backup", s: "Export and import appliance configuration and database" }
    };

    if (titleMap[targetId]) {
        document.getElementById("page-header-title").textContent = titleMap[targetId].t;
        document.getElementById("page-header-subtitle").textContent = titleMap[targetId].s;
    }

    // Trigger tab-specific fetches
    if (targetId === "view-dashboard" || targetId === "view-ipam") fetchIpamSubnets();
    if (targetId === "view-dns") fetchDns();
    if (targetId === "view-dhcp") fetchDhcp();
    if (targetId === "view-radius") fetchRadius();
    if (targetId === "view-tacacs") fetchTacacs();
    if (targetId === "view-ldap") fetchLdap();
    if (targetId === "view-ntp") fetchNtp();
    if (targetId === "view-files") fetchFiles();
    if (targetId === "view-interfaces") fetchNetworkInterfaces();
}

// --- Status & Statistics Polling ---
async function fetchStatus() {
    try {
        const response = await fetch("/api/status");
        if (!response.ok) throw new Error("API Connection Error");
        const data = await response.json();

        // Update Connection Badge
        const connBadge = document.getElementById("connection-status");
        connBadge.className = "status-indicator active";
        connBadge.innerHTML = '<div class="status-dot"></div>Connected';

        // Update Sidebar/Stats
        document.getElementById("sb-uptime").textContent = formatUptime(data.system.uptime);
        
        // Show IP list
        const ipString = Object.entries(data.system.ips)
            .map(([ifname, ip]) => `${ifname}: ${ip}`)
            .join(" | ");
        document.getElementById("sb-ip").textContent = ipString || "127.0.0.1";

        // Update Placeholders in CLI commands
        const defaultIp = Object.values(data.system.ips)[0] || "127.0.0.1";
        document.querySelectorAll(".server-ip-placeholder").forEach(el => el.textContent = defaultIp);

        // Update dashboard widget values
        document.getElementById("stat-cpu").textContent = data.system.cpu_load[0].toFixed(2);
        document.getElementById("stat-ram").textContent = `${data.system.ram_pct}%`;
        document.getElementById("stat-disk").textContent = `${data.system.disk_pct}%`;
        document.getElementById("stat-uptime").textContent = formatUptime(data.system.uptime);

        // Update Service Widgets status checkboxes & badges
        updateServiceState("syslog", data.services.syslog);
        updateServiceState("dns", data.services.dns);
        updateServiceState("dhcp", data.services.dhcp);
        updateServiceState("radius", data.services.radius);
        updateServiceState("tacacs", data.services.tacacs);
        updateServiceState("ldap", data.services.ldap);

        applyRoleRestrictions();

    } catch (error) {
        // Show Connection offline badge
        const connBadge = document.getElementById("connection-status");
        connBadge.className = "status-indicator inactive";
        connBadge.innerHTML = '<div class="status-dot"></div>Disconnected';
    }
}

function updateServiceState(name, serviceData) {
    // Toggle switch checkbox
    const toggle = document.getElementById(`toggle-${name}`);
    if (toggle) {
        toggle.checked = serviceData.enabled;
    }

    // Status Badge
    const badge = document.getElementById(`badge-${name}`);
    if (badge) {
        if (serviceData.running) {
            badge.className = "status-indicator active";
            badge.innerHTML = `<div class="status-dot"></div>Running (Port ${serviceData.port})`;
        } else {
            badge.className = "status-indicator inactive";
            badge.innerHTML = `<div class="status-dot"></div>Stopped`;
        }
    }
}

// --- Toggle Service ---
async function toggleService(name) {
    const toggle = document.getElementById(`toggle-${name}`);
    const isEnabled = toggle.checked;

    try {
        const response = await fetch(`/api/services/${name}/toggle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: isEnabled })
        });
        if (!response.ok) {
            const errorMsg = await parseResponseError(response, "Failed to toggle service");
            throw new Error(errorMsg);
        }
        fetchStatus();
    } catch (error) {
        alert(error.message);
        toggle.checked = !isEnabled; // Revert switch UI state
    }
}

// --- IPAM (IP Address Management) Functions ---
let currentIpamSubnets = [];

async function fetchIpamSubnets() {
    const tbody = document.getElementById("ipam-subnets-tbody");
    if (!tbody) return;

    try {
        const response = await fetch("/api/ipam/subnets");
        if (!response.ok) return;
        currentIpamSubnets = await response.json();

        // Update Dashboard Summary Stats
        let totalSubnets = currentIpamSubnets.length;
        let totalAllocated = 0;
        let totalUsable = 0;

        currentIpamSubnets.forEach(s => {
            totalAllocated += s.allocated_ips;
            totalUsable += s.usable_ips;
        });

        const dashSubnetsEl = document.getElementById("dash-ipam-subnets-count");
        if (dashSubnetsEl) dashSubnetsEl.textContent = totalSubnets;

        const dashAllocEl = document.getElementById("dash-ipam-allocated-count");
        if (dashAllocEl) dashAllocEl.textContent = totalAllocated;

        const dashUsableEl = document.getElementById("dash-ipam-usable-count");
        if (dashUsableEl) dashUsableEl.textContent = totalUsable;

        if (currentIpamSubnets.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No IPAM subnets configured. Click "+ Add Subnet" to create one.</td></tr>';
            return;
        }

        tbody.innerHTML = currentIpamSubnets.map(s => {
            const pct = s.usage_pct || 0;
            const barColor = pct > 90 ? "var(--danger)" : pct > 75 ? "var(--warning)" : "#10b981";

            const progressHtml = `
                <div style="background: rgba(255,255,255,0.08); border-radius: 6px; height: 16px; width: 100px; overflow: hidden; position: relative; display: inline-block; vertical-align: middle;">
                    <div style="width: ${pct}%; background: ${barColor}; height: 100%; transition: width 0.3s ease;"></div>
                    <span style="position: absolute; top:0; left: 0; right: 0; bottom: 0; font-size: 10px; font-weight: 700; color: #fff; text-shadow: 0 0 2px #000; display: flex; align-items: center; justify-content: center;">${pct}%</span>
                </div>
            `;

            return `
                <tr>
                    <td><strong style="font-size: 14px;">${escapeHtml(s.name)}</strong></td>
                    <td><code style="font-family: monospace; font-size: 13px; color: var(--accent);">${escapeHtml(s.cidr)}</code></td>
                    <td>${s.vlan_id ? `<span class="badge badge-info">VLAN ${s.vlan_id}</span>` : '<span style="color: var(--text-muted);">-</span>'}</td>
                    <td><span style="font-family: monospace; font-size: 12px; color: var(--text-secondary);">${escapeHtml(s.vrf || "default")}</span></td>
                    <td><span style="font-family: monospace; font-size: 12px;">${escapeHtml(s.gateway || "-")}</span></td>
                    <td>${progressHtml}</td>
                    <td><strong style="color: #10b981;">${s.allocated_ips}</strong> / ${s.usable_ips}</td>
                    <td style="text-align: center; white-space: nowrap;">
                        <button class="btn btn-secondary btn-sm" style="padding: 4px 8px; margin-right: 4px;" onclick="viewSubnetDetail(${s.id})">🔍 View IPs</button>
                        <button class="btn btn-danger btn-sm" style="padding: 4px 8px;" onclick="deleteIpamSubnet(${s.id})">Delete</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        console.error("Error fetching IPAM subnets:", err);
    }
}

function openAddSubnetModal() {
    document.getElementById("form-ipam-subnet").reset();
    document.getElementById("modal-ipam-subnet").classList.add("active");
}

function closeAddSubnetModal() {
    document.getElementById("modal-ipam-subnet").classList.remove("active");
}

async function saveIpamSubnet(event) {
    event.preventDefault();
    const name = document.getElementById("subnet-name").value;
    const cidr = document.getElementById("subnet-cidr").value;
    const vlan = document.getElementById("subnet-vlan").value;
    const vrf = document.getElementById("subnet-vrf").value;
    const gateway = document.getElementById("subnet-gateway").value;
    const desc = document.getElementById("subnet-desc").value;

    try {
        const response = await fetch("/api/ipam/subnets", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name,
                cidr,
                vlan_id: vlan ? parseInt(vlan) : null,
                vrf: vrf || "default",
                gateway,
                description: desc
            })
        });

        if (!response.ok) {
            const errorMsg = await parseResponseError(response, "Failed to add subnet");
            alert(errorMsg);
            return;
        }

        closeAddSubnetModal();
        fetchIpamSubnets();
    } catch (err) {
        alert("Error creating subnet: " + err.message);
    }
}

async function deleteIpamSubnet(subnetId) {
    if (!confirm("Are you sure you want to delete this subnet and all its IP allocations?")) return;
    try {
        const response = await fetch(`/api/ipam/subnets/${subnetId}`, { method: "DELETE" });
        if (!response.ok) throw new Error("Failed to delete subnet");
        
        closeSubnetDetail();
        fetchIpamSubnets();
    } catch (err) {
        alert("Error deleting subnet: " + err.message);
    }
}

let activeSubnetDetailId = null;

async function viewSubnetDetail(subnetId) {
    activeSubnetDetailId = subnetId;
    const card = document.getElementById("subnet-detail-card");
    const tbody = document.getElementById("subnet-addrs-tbody");
    card.style.display = "block";
    card.scrollIntoView({ behavior: 'smooth' });

    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Loading IP matrix...</td></tr>';

    try {
        const response = await fetch(`/api/ipam/subnets/${subnetId}/addresses`);
        if (!response.ok) throw new Error("Failed to load subnet IP matrix");
        const data = await response.json();

        const s = data.subnet;
        document.getElementById("subnet-detail-title").textContent = `IP Matrix: ${s.name} (${s.cidr})`;
        document.getElementById("subnet-detail-info").innerHTML = `
            <strong>VLAN:</strong> ${s.vlan_id || "None"} &nbsp;|&nbsp; 
            <strong>VRF:</strong> ${s.vrf || "default"} &nbsp;|&nbsp; 
            <strong>Gateway:</strong> ${s.gateway || "None"} &nbsp;|&nbsp; 
            <strong>Description:</strong> ${escapeHtml(s.description || "N/A")}
        `;

        if (!data.addresses || data.addresses.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No IP addresses in subnet.</td></tr>';
            return;
        }

        tbody.innerHTML = data.addresses.map(a => {
            let statusBadge = "";
            switch (a.status) {
                case "active":
                    statusBadge = '<span class="badge badge-success">🟢 Active</span>';
                    break;
                case "dhcp":
                    statusBadge = '<span class="badge badge-info">🔵 DHCP Leased</span>';
                    break;
                case "dhcp_static":
                    statusBadge = '<span class="badge badge-primary">🟣 DHCP Reserved</span>';
                    break;
                case "reserved":
                    statusBadge = '<span class="badge badge-warning">🟡 Reserved</span>';
                    break;
                default:
                    statusBadge = '<span class="badge badge-secondary" style="opacity: 0.5;">⚪ Available</span>';
                    break;
            }

            return `
                <tr style="${a.status === 'available' ? 'opacity: 0.75;' : ''}">
                    <td><strong style="font-family: monospace; font-size: 13px;">${escapeHtml(a.ip_address)}</strong></td>
                    <td>${statusBadge}</td>
                    <td>${escapeHtml(a.hostname || "-")}</td>
                    <td><code style="font-family: monospace; font-size: 12px; color: var(--text-secondary);">${escapeHtml(a.mac_address || "-")}</code></td>
                    <td>${escapeHtml(a.description || "-")}</td>
                    <td><span style="font-size: 11px; color: var(--text-muted);">${escapeHtml(a.last_seen || "-")}</span></td>
                    <td style="text-align: center;">
                        <button class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 12px;" 
                            onclick="openEditAddressModal(${s.id}, '${escapeHtml(a.ip_address)}', '${escapeHtml(a.status)}', '${escapeHtml(a.hostname || '')}', '${escapeHtml(a.mac_address || '')}', '${escapeHtml(a.description || '')}')">
                            Edit / Reserve
                        </button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--danger);">${escapeHtml(err.message)}</td></tr>`;
    }
}

function closeSubnetDetail() {
    document.getElementById("subnet-detail-card").style.display = "none";
    activeSubnetDetailId = null;
}

function openEditAddressModal(subnetId, ipAddress, currentStatus, hostname, mac, desc) {
    document.getElementById("ipam-addr-subnet-id").value = subnetId;
    document.getElementById("ipam-addr-ip").value = ipAddress;
    document.getElementById("ipam-addr-status").value = (currentStatus === "available" || !currentStatus) ? "active" : currentStatus;
    document.getElementById("ipam-addr-host").value = hostname || "";
    document.getElementById("ipam-addr-mac").value = mac || "";
    document.getElementById("ipam-addr-desc").value = desc || "";

    document.getElementById("modal-ipam-address").classList.add("active");
}

function closeEditAddressModal() {
    document.getElementById("modal-ipam-address").classList.remove("active");
}

async function submitIpamAddress(event) {
    event.preventDefault();
    const subnetId = parseInt(document.getElementById("ipam-addr-subnet-id").value);
    const ip = document.getElementById("ipam-addr-ip").value;
    const status = document.getElementById("ipam-addr-status").value;
    const host = document.getElementById("ipam-addr-host").value;
    const mac = document.getElementById("ipam-addr-mac").value;
    const desc = document.getElementById("ipam-addr-desc").value;

    try {
        const response = await fetch("/api/ipam/addresses", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                subnet_id: subnetId,
                ip_address: ip,
                status: status,
                hostname: host,
                mac_address: mac,
                description: desc
            })
        });

        if (!response.ok) {
            const errorMsg = await parseResponseError(response, "Failed to save IP allocation");
            alert(errorMsg);
            return;
        }

        closeEditAddressModal();
        fetchIpamSubnets();
        if (activeSubnetDetailId === subnetId) {
            viewSubnetDetail(subnetId);
        }
    } catch (err) {
        alert("Error saving IP allocation: " + err.message);
    }
}

async function syncIpam() {
    try {
        const response = await fetch("/api/ipam/sync", { method: "POST" });
        if (!response.ok) throw new Error("Sync failed");
        const res = await response.json();
        alert(res.message || "IPAM synced successfully!");
        fetchIpamSubnets();
        if (activeSubnetDetailId) {
            viewSubnetDetail(activeSubnetDetailId);
        }
    } catch (err) {
        alert("Error auto-syncing IPAM: " + err.message);
    }
}

async function searchIpam() {
    const q = document.getElementById("ipam-search-input").value.trim();
    const container = document.getElementById("ipam-search-results");
    const tbody = document.getElementById("ipam-search-tbody");

    if (!q) {
        container.style.display = "none";
        return;
    }

    try {
        const response = await fetch(`/api/ipam/search?q=${encodeURIComponent(q)}`);
        if (!response.ok) return;
        const results = await response.json();

        container.style.display = "block";
        if (results.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No IP allocations found matching query.</td></tr>';
            return;
        }

        tbody.innerHTML = results.map(r => `
            <tr>
                <td><strong style="font-size: 12px;">${escapeHtml(r.subnet_name)} (${escapeHtml(r.subnet_cidr)})</strong></td>
                <td><code style="font-family: monospace;">${escapeHtml(r.ip_address)}</code></td>
                <td><span class="badge badge-info">${escapeHtml(r.status)}</span></td>
                <td>${escapeHtml(r.hostname || "-")}</td>
                <td><code style="font-size: 11px;">${escapeHtml(r.mac_address || "-")}</code></td>
                <td>${escapeHtml(r.description || "-")}</td>
            </tr>
        `).join("");
    } catch (err) {
        console.error("Search error:", err);
    }
}

// --- DNS Functions ---
async function fetchDns() {
    const res = await fetch("/api/dns");
    const data = await res.json();

    document.getElementById("dns-upstream").value = data.upstream;
    
    const tbody = document.getElementById("dns-records-table");
    if (data.records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No local records configured</td></tr>';
        return;
    }

    tbody.innerHTML = data.records.map(rec => `
        <tr>
            <td>${escapeHtml(rec.hostname)}</td>
            <td>${escapeHtml(rec.ip_address)}</td>
            <td>A</td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteDnsRecord('${rec.hostname}')">Delete</button></td>
        </tr>
    `).join("");
}

async function saveDnsSettings(e) {
    e.preventDefault();
    const upstream = document.getElementById("dns-upstream").value;
    const enabled = document.getElementById("toggle-dns").checked;

    await fetch("/api/dns/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, upstream })
    });
    alert("DNS Upstream settings updated successfully.");
    fetchDns();
}

async function addDnsRecord(e) {
    e.preventDefault();
    const hostname = document.getElementById("dns-hostname").value.trim();
    const ip_address = document.getElementById("dns-ip").value.trim();

    const res = await fetch("/api/dns/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hostname, ip_address })
    });
    if (res.ok) {
        document.getElementById("dns-hostname").value = "";
        document.getElementById("dns-ip").value = "";
        fetchDns();
    } else {
        const errorMsg = await parseResponseError(res, "Failed to add DNS record");
        alert(errorMsg);
    }
}

async function deleteDnsRecord(hostname) {
    await fetch(`/api/dns/records/${hostname}`, { method: "DELETE" });
    fetchDns();
}

// --- DHCP Functions ---
let currentDhcpRanges = [];

async function fetchDhcp() {
    const res = await fetch("/api/dhcp");
    const data = await res.json();

    const ifaceInput = document.getElementById("dhcp-interface");
    if (ifaceInput) ifaceInput.value = data.interface || "eth0";

    currentDhcpRanges = data.ranges || [];

    // Render DHCP Scopes Table
    const scopesTbody = document.getElementById("dhcp-scopes-table");
    if (scopesTbody) {
        if (currentDhcpRanges.length === 0) {
            scopesTbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No DHCP scopes configured. Click "+ Create New Scope" to add one.</td></tr>';
        } else {
            scopesTbody.innerHTML = currentDhcpRanges.map(scope => {
                const rangeStr = `${escapeHtml(scope.start_ip)} &rarr; ${escapeHtml(scope.end_ip)}`;
                const dnsDom = [scope.dns_servers, scope.domain_name].filter(Boolean).map(escapeHtml).join(" / ") || "-";
                
                let specialOpts = [];
                if (scope.primary_wlc) {
                    let wlcList = [scope.primary_wlc, scope.secondary_wlc, scope.tertiary_wlc].filter(Boolean).map(escapeHtml).join(", ");
                    specialOpts.push(`<span class="status-indicator active" style="font-size: 11px; padding: 2px 8px;">WLC: ${wlcList}</span>`);
                } else if (scope.option_43_hex) {
                    specialOpts.push(`<span class="status-indicator active" style="font-size: 11px; padding: 2px 8px;">Opt 43 Hex</span>`);
                }
                if (scope.tftp_server) specialOpts.push(`<span class="status-indicator" style="font-size: 11px; padding: 2px 8px;">TFTP: ${escapeHtml(scope.tftp_server)}</span>`);
                if (scope.ntp_servers) specialOpts.push(`<span class="status-indicator" style="font-size: 11px; padding: 2px 8px;">NTP: ${escapeHtml(scope.ntp_servers)}</span>`);
                if (scope.custom_options) specialOpts.push(`<span class="status-indicator" style="font-size: 11px; padding: 2px 8px;">Custom</span>`);
                
                const optsHtml = specialOpts.length > 0 ? specialOpts.join(" ") : "-";

                return `
                    <tr>
                        <td><strong>${escapeHtml(scope.name)}</strong></td>
                        <td><span style="font-family: monospace;">${rangeStr}</span></td>
                        <td><span style="font-family: monospace;">${escapeHtml(scope.netmask)}</span></td>
                        <td>${escapeHtml(scope.gateway || "-")}</td>
                        <td>${dnsDom}</td>
                        <td>${optsHtml}</td>
                        <td>
                            <button class="btn btn-secondary btn-sm" style="padding: 4px 8px;" onclick="openEditScopeModal(${scope.id})">Edit</button>
                            <button class="btn btn-danger btn-sm" style="padding: 4px 8px;" onclick="deleteDhcpScope(${scope.id})">&times;</button>
                        </td>
                    </tr>
                `;
            }).join("");
        }
    }

    // Render static leases pool
    const staticTbody = document.getElementById("dhcp-static-table");
    if (staticTbody) {
        if (data.static_leases.length === 0) {
            staticTbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No static leases configured</td></tr>';
        } else {
            staticTbody.innerHTML = data.static_leases.map(lease => `
                <tr>
                    <td><span style="font-family: monospace;">${lease.mac_address}</span></td>
                    <td>${lease.ip_address}</td>
                    <td>${escapeHtml(lease.hostname || "-")}</td>
                    <td><button class="btn btn-danger btn-sm" onclick="deleteDhcpStatic('${lease.mac_address}')">&times;</button></td>
                </tr>
            `).join("");
        }
    }

    // Render active leases
    const activeTbody = document.getElementById("dhcp-leases-table");
    if (activeTbody) {
        if (data.active_leases.length === 0) {
            activeTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No active leases found</td></tr>';
        } else {
            activeTbody.innerHTML = data.active_leases.map(lease => `
                <tr>
                    <td><span style="font-family: monospace;">${lease.mac}</span></td>
                    <td>${lease.ip}</td>
                    <td>${escapeHtml(lease.hostname || "-")}</td>
                </tr>
            `).join("");
        }
    }
}

async function saveDhcpGlobalSettings(e) {
    e.preventDefault();
    const interface = document.getElementById("dhcp-interface").value;
    await fetch("/api/dhcp/global-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interface })
    });
    alert("Global DHCP interface settings saved.");
    fetchDhcp();
}

function openAddScopeModal() {
    document.getElementById("scope-id").value = "";
    document.getElementById("modal-dhcp-scope-title").textContent = "Create DHCP Scope";
    document.getElementById("scope-name").value = "";
    document.getElementById("scope-start").value = "";
    document.getElementById("scope-end").value = "";
    document.getElementById("scope-netmask").value = "255.255.255.0";
    document.getElementById("scope-gateway").value = "";
    document.getElementById("scope-dns").value = "";
    document.getElementById("scope-domain").value = "";
    document.getElementById("scope-lease").value = "12h";
    document.getElementById("scope-wlc-primary").value = "";
    document.getElementById("scope-wlc-secondary").value = "";
    document.getElementById("scope-wlc-tertiary").value = "";
    document.getElementById("scope-opt43-hex").value = "";
    document.getElementById("scope-ntp").value = "";
    document.getElementById("scope-tftp").value = "";
    document.getElementById("scope-custom-options").value = "";
    document.getElementById("modal-dhcp-scope").classList.add("active");
}

function openEditScopeModal(scopeId) {
    const scope = currentDhcpRanges.find(r => r.id === scopeId);
    if (!scope) return;

    document.getElementById("scope-id").value = scope.id;
    document.getElementById("modal-dhcp-scope-title").textContent = `Edit Scope: ${scope.name}`;
    document.getElementById("scope-name").value = scope.name || "";
    document.getElementById("scope-start").value = scope.start_ip || "";
    document.getElementById("scope-end").value = scope.end_ip || "";
    document.getElementById("scope-netmask").value = scope.netmask || "255.255.255.0";
    document.getElementById("scope-gateway").value = scope.gateway || "";
    document.getElementById("scope-dns").value = scope.dns_servers || "";
    document.getElementById("scope-domain").value = scope.domain_name || "";
    document.getElementById("scope-lease").value = scope.lease_time || "12h";
    document.getElementById("scope-wlc-primary").value = scope.primary_wlc || "";
    document.getElementById("scope-wlc-secondary").value = scope.secondary_wlc || "";
    document.getElementById("scope-wlc-tertiary").value = scope.tertiary_wlc || "";
    document.getElementById("scope-opt43-hex").value = scope.option_43_hex || "";
    document.getElementById("scope-ntp").value = scope.ntp_servers || "";
    document.getElementById("scope-tftp").value = scope.tftp_server || "";
    document.getElementById("scope-custom-options").value = scope.custom_options || "";
    document.getElementById("modal-dhcp-scope").classList.add("active");
}

function closeScopeModal() {
    document.getElementById("modal-dhcp-scope").classList.remove("active");
}

async function saveScopeForm(e) {
    e.preventDefault();
    const scopeId = document.getElementById("scope-id").value;
    const payload = {
        name: document.getElementById("scope-name").value.trim(),
        start_ip: document.getElementById("scope-start").value.trim(),
        end_ip: document.getElementById("scope-end").value.trim(),
        netmask: document.getElementById("scope-netmask").value.trim(),
        gateway: document.getElementById("scope-gateway").value.trim(),
        dns_servers: document.getElementById("scope-dns").value.trim(),
        domain_name: document.getElementById("scope-domain").value.trim(),
        lease_time: document.getElementById("scope-lease").value.trim(),
        primary_wlc: document.getElementById("scope-wlc-primary").value.trim(),
        secondary_wlc: document.getElementById("scope-wlc-secondary").value.trim(),
        tertiary_wlc: document.getElementById("scope-wlc-tertiary").value.trim(),
        option_43_hex: document.getElementById("scope-opt43-hex").value.trim(),
        ntp_servers: document.getElementById("scope-ntp").value.trim(),
        tftp_server: document.getElementById("scope-tftp").value.trim(),
        custom_options: document.getElementById("scope-custom-options").value.trim()
    };

    let url = "/api/dhcp/ranges";
    let method = "POST";
    if (scopeId) {
        url = `/api/dhcp/ranges/${scopeId}`;
        method = "PUT";
    }

    const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });

    if (res.ok) {
        closeScopeModal();
        fetchDhcp();
    } else {
        const err = await res.json();
        alert("Error saving scope: " + (err.detail || "Failed"));
    }
}

async function deleteDhcpScope(scopeId) {
    if (!confirm("Are you sure you want to delete this DHCP scope?")) return;
    const res = await fetch(`/api/dhcp/ranges/${scopeId}`, { method: "DELETE" });
    if (res.ok) {
        fetchDhcp();
    } else {
        alert("Failed to delete scope.");
    }
}

async function addDhcpStatic(e) {
    e.preventDefault();
    const mac_address = document.getElementById("dhcp-static-mac").value.trim();
    const ip_address = document.getElementById("dhcp-static-ip").value.trim();
    const hostname = document.getElementById("dhcp-static-name").value.trim();

    const res = await fetch("/api/dhcp/static", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mac_address, ip_address, hostname })
    });

    if (res.ok) {
        document.getElementById("dhcp-static-mac").value = "";
        document.getElementById("dhcp-static-ip").value = "";
        document.getElementById("dhcp-static-name").value = "";
        fetchDhcp();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteDhcpStatic(mac) {
    await fetch(`/api/dhcp/static/${mac}`, { method: "DELETE" });
    fetchDhcp();
}

// --- RADIUS Functions ---
async function fetchRadius() {
    const res = await fetch("/api/radius");
    const data = await res.json();

    // Render clients
    const clientsTbody = document.getElementById("radius-clients-table");
    if (data.clients.length === 0) {
        clientsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No clients configured</td></tr>';
    } else {
        clientsTbody.innerHTML = data.clients.map(cli => `
            <tr>
                <td>${escapeHtml(cli.ip_network)}</td>
                <td>${escapeHtml(cli.name || "-")}</td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteRadiusClient('${cli.ip_network}')">&times;</button></td>
            </tr>
        `).join("");
    }

    // Render users
    const usersTbody = document.getElementById("radius-users-table");
    if (data.users.length === 0) {
        usersTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No users configured</td></tr>';
    } else {
        usersTbody.innerHTML = data.users.map(usr => `
            <tr>
                <td>${escapeHtml(usr.username)}</td>
                <td><span style="font-family: monospace;">${escapeHtml(usr.password)}</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteRadiusUser('${usr.username}')">&times;</button></td>
            </tr>
        `).join("");
    }

    // Fetch auth logs too
    fetchAuthLogs();
}

async function addRadiusClient(e) {
    e.preventDefault();
    const ip_network = document.getElementById("rad-client-ip").value.trim();
    const shared_secret = document.getElementById("rad-client-secret").value.trim();
    const name = document.getElementById("rad-client-name").value.trim();

    const res = await fetch("/api/radius/clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip_network, shared_secret, name })
    });
    if (res.ok) {
        document.getElementById("rad-client-ip").value = "";
        document.getElementById("rad-client-secret").value = "";
        document.getElementById("rad-client-name").value = "";
        fetchRadius();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteRadiusClient(ipNet) {
    await fetch(`/api/radius/clients/${ipNet}`, { method: "DELETE" });
    fetchRadius();
}

async function addRadiusUser(e) {
    e.preventDefault();
    const username = document.getElementById("rad-username").value.trim();
    const password = document.getElementById("rad-password").value.trim();

    const res = await fetch("/api/radius/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
    });
    if (res.ok) {
        document.getElementById("rad-username").value = "";
        document.getElementById("rad-password").value = "";
        fetchRadius();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteRadiusUser(username) {
    await fetch(`/api/radius/users/${username}`, { method: "DELETE" });
    fetchRadius();
}

// --- TACACS+ Functions ---
async function fetchTacacs() {
    const res = await fetch("/api/tacacs");
    const data = await res.json();

    // Render clients
    const clientsTbody = document.getElementById("tacacs-clients-table");
    if (data.clients.length === 0) {
        clientsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No clients configured</td></tr>';
    } else {
        clientsTbody.innerHTML = data.clients.map(cli => `
            <tr>
                <td>${escapeHtml(cli.ip_network)}</td>
                <td>${escapeHtml(cli.name || "-")}</td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteTacacsClient('${cli.ip_network}')">&times;</button></td>
            </tr>
        `).join("");
    }

    // Render users
    const usersTbody = document.getElementById("tacacs-users-table");
    if (data.users.length === 0) {
        usersTbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No users configured</td></tr>';
    } else {
        usersTbody.innerHTML = data.users.map(usr => `
            <tr>
                <td><strong style="font-size: 13px;">${escapeHtml(usr.username)}</strong></td>
                <td><span class="status-indicator active" style="padding: 2px 8px; font-size: 11px;">Privilege ${usr.privilege}</span></td>
                <td><span class="badge ${usr.default_action === 'deny' ? 'badge-danger' : 'badge-success'}">${escapeHtml((usr.default_action || 'permit').toUpperCase())}</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteTacacsUser('${usr.username}')">&times;</button></td>
            </tr>
        `).join("");
    }

    // Populate user dropdowns for rule creation and simulation
    const ruleUserDropdown = document.getElementById("tac-rule-user");
    const simUserDropdown = document.getElementById("tac-sim-user");
    if (ruleUserDropdown && simUserDropdown) {
        const userOpts = data.users.map(u => `<option value="${escapeHtml(u.username)}">${escapeHtml(u.username)} (Priv ${u.privilege})</option>`).join("");
        ruleUserDropdown.innerHTML = userOpts || '<option value="">No users available</option>';
        simUserDropdown.innerHTML = userOpts || '<option value="">No users available</option>';
    }

    fetchTacacsRules();
}

async function fetchTacacsRules() {
    const tbody = document.getElementById("tacacs-rules-table");
    if (!tbody) return;

    try {
        const res = await fetch("/api/tacacs/rules");
        if (!res.ok) return;
        const rules = await res.json();

        if (rules.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No command authorization rules configured.</td></tr>';
            return;
        }

        tbody.innerHTML = rules.map(r => `
            <tr>
                <td><strong>${escapeHtml(r.username)}</strong></td>
                <td><code style="font-family: monospace; color: var(--accent);">${escapeHtml(r.command)}</code></td>
                <td><code style="font-family: monospace; font-size: 11px;">${escapeHtml(r.argument_regex)}</code></td>
                <td><span class="badge ${r.action === 'deny' ? 'badge-danger' : 'badge-success'}">${escapeHtml(r.action.toUpperCase())}</span></td>
                <td><button class="btn btn-danger btn-sm" style="padding: 2px 6px;" onclick="deleteTacacsRule(${r.id})">&times;</button></td>
            </tr>
        `).join("");
    } catch (e) {
        console.error("Error fetching TACACS+ rules:", e);
    }
}

async function addTacacsClient(e) {
    e.preventDefault();
    const ip_network = document.getElementById("tac-client-ip").value.trim();
    const shared_secret = document.getElementById("tac-client-secret").value.trim();
    const name = document.getElementById("tac-client-name").value.trim();

    const res = await fetch("/api/tacacs/clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip_network, shared_secret, name })
    });
    if (res.ok) {
        document.getElementById("tac-client-ip").value = "";
        document.getElementById("tac-client-secret").value = "";
        document.getElementById("tac-client-name").value = "";
        fetchTacacs();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteTacacsClient(ipNet) {
    await fetch(`/api/tacacs/clients/${ipNet}`, { method: "DELETE" });
    fetchTacacs();
}

async function addTacacsUser(e) {
    e.preventDefault();
    const username = document.getElementById("tac-username").value.trim();
    const password = document.getElementById("tac-password").value.trim();
    const privilege = parseInt(document.getElementById("tac-privilege").value);
    const default_action = document.getElementById("tac-default-action").value;

    const res = await fetch("/api/tacacs/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, privilege, default_action })
    });
    if (res.ok) {
        document.getElementById("tac-username").value = "";
        document.getElementById("tac-password").value = "";
        fetchTacacs();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteTacacsUser(username) {
    await fetch(`/api/tacacs/users/${username}`, { method: "DELETE" });
    fetchTacacs();
}

async function addTacacsRule(e) {
    e.preventDefault();
    const username = document.getElementById("tac-rule-user").value;
    const command = document.getElementById("tac-rule-cmd").value.trim();
    const regex = document.getElementById("tac-rule-regex").value.trim();
    const action = document.getElementById("tac-rule-action").value;

    if (!username) {
        alert("Please select a user first.");
        return;
    }

    try {
        const res = await fetch("/api/tacacs/rules", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, command, argument_regex: regex, action })
        });
        if (res.ok) {
            document.getElementById("tac-rule-cmd").value = "";
            document.getElementById("tac-rule-regex").value = ".*";
            fetchTacacsRules();
        } else {
            const err = await res.json();
            alert(err.detail);
        }
    } catch (err) {
        alert("Error adding TACACS+ rule: " + err.message);
    }
}

async function deleteTacacsRule(ruleId) {
    await fetch(`/api/tacacs/rules/${ruleId}`, { method: "DELETE" });
    fetchTacacsRules();
}

async function simulateTacacsAuth(e) {
    e.preventDefault();
    const username = document.getElementById("tac-sim-user").value;
    const command = document.getElementById("tac-sim-cmd").value.trim();

    if (!username) {
        alert("Please select a user to test.");
        return;
    }

    try {
        const res = await fetch("/api/tacacs/test-authorization", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, command })
        });
        if (!res.ok) throw new Error("Authorization test failed");
        const data = await res.json();

        const verdictBox = document.getElementById("tacacs-sim-verdict");
        const titleEl = document.getElementById("tac-verdict-title");
        const badgeEl = document.getElementById("tac-verdict-badge");
        const detailsEl = document.getElementById("tac-verdict-details");

        verdictBox.style.display = "block";

        if (data.status === "PERMITTED") {
            verdictBox.style.borderColor = "#10b981";
            verdictBox.style.background = "rgba(16, 185, 129, 0.08)";
            titleEl.style.color = "#10b981";
            titleEl.textContent = "✅ AUTHORIZATION PERMITTED";
            badgeEl.className = "badge badge-success";
            badgeEl.textContent = "TAC_PLUS_AUTHOR_STATUS_PASS";
        } else {
            verdictBox.style.borderColor = "var(--danger)";
            verdictBox.style.background = "rgba(239, 68, 68, 0.08)";
            titleEl.style.color = "var(--danger)";
            titleEl.textContent = "⛔ AUTHORIZATION DENIED";
            badgeEl.className = "badge badge-danger";
            badgeEl.textContent = "TAC_PLUS_AUTHOR_STATUS_FAIL";
        }

        detailsEl.innerHTML = `
            <strong>User:</strong> ${escapeHtml(data.username)} (Privilege ${data.privilege})<br>
            <strong>Tested Command:</strong> <code style="color: var(--accent);">${escapeHtml(data.command)}</code><br>
            <strong>Matched Rule:</strong> <code style="font-size: 11px;">${escapeHtml(data.matched_rule)}</code><br>
            <strong>Reasoning:</strong> ${escapeHtml(data.reason)}
        `;
    } catch (err) {
        alert("Error running authorization simulation: " + err.message);
    }
}

// --- LDAP Functions ---
async function fetchLdap() {
    const res = await fetch("/api/ldap");
    const data = await res.json();

    document.getElementById("ldap-port").value = data.port;
    document.getElementById("ldap-base").value = data.base_dn;
    document.getElementById("ldap-root").value = data.root_dn;

    // Render LDAP Users Table
    const usersTbody = document.getElementById("ldap-users-table");
    if (data.users.length === 0) {
        usersTbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No users defined</td></tr>';
    } else {
        usersTbody.innerHTML = data.users.map(usr => `
            <tr>
                <td>cn=${escapeHtml(usr.username)},ou=users,${escapeHtml(data.base_dn)}</td>
                <td>${escapeHtml(usr.email || "-")}</td>
                <td>${escapeHtml(usr.first_name || "-")}</td>
                <td>${escapeHtml(usr.last_name || "-")}</td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteLdapUser('${usr.username}')">&times;</button></td>
            </tr>
        `).join("");
    }

    // Render LDAP Groups Table
    const groupsTbody = document.getElementById("ldap-groups-table");
    if (data.groups.length === 0) {
        groupsTbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No groups defined</td></tr>';
    } else {
        groupsTbody.innerHTML = data.groups.map(grp => `
            <tr>
                <td>cn=${escapeHtml(grp.group_name)},ou=groups,${escapeHtml(data.base_dn)}</td>
                <td>
                    <span style="font-size: 12px; color: var(--text-secondary); max-width: 250px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        ${grp.members.length > 0 ? grp.members.join(", ") : "no members"}
                    </span>
                </td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="manageMembers('${grp.group_name}', ${JSON.stringify(grp.members)})">Members</button>
                    <button class="btn btn-danger btn-sm" style="padding: 4px 8px;" onclick="deleteLdapGroup('${grp.group_name}')">&times;</button>
                </td>
            </tr>
        `).join("");
    }
}

async function saveLdapSettings(e) {
    e.preventDefault();
    const port = document.getElementById("ldap-port").value;
    const base_dn = document.getElementById("ldap-base").value;
    const root_dn = document.getElementById("ldap-root").value;
    const root_password = document.getElementById("ldap-root-password").value;
    const enabled = document.getElementById("toggle-ldap").checked;

    await fetch("/api/ldap/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, port, base_dn, root_dn, root_password })
    });
    alert("LDAP Settings updated successfully.");
    fetchLdap();
}

async function addLdapUser(e) {
    e.preventDefault();
    const username = document.getElementById("ldap-user-name").value.trim();
    const password = document.getElementById("ldap-user-password").value.trim();
    const first_name = document.getElementById("ldap-user-fname").value.trim();
    const last_name = document.getElementById("ldap-user-lname").value.trim();
    const email = document.getElementById("ldap-user-email").value.trim();

    const res = await fetch("/api/ldap/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, first_name, last_name, email })
    });
    if (res.ok) {
        document.getElementById("ldap-user-name").value = "";
        document.getElementById("ldap-user-password").value = "";
        document.getElementById("ldap-user-fname").value = "";
        document.getElementById("ldap-user-lname").value = "";
        document.getElementById("ldap-user-email").value = "";
        fetchLdap();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteLdapUser(username) {
    await fetch(`/api/ldap/users/${username}`, { method: "DELETE" });
    fetchLdap();
}

async function addLdapGroup(e) {
    e.preventDefault();
    const group_name = document.getElementById("ldap-group-name").value.trim();
    const description = document.getElementById("ldap-group-desc").value.trim();

    const res = await fetch("/api/ldap/groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_name, description })
    });
    if (res.ok) {
        document.getElementById("ldap-group-name").value = "";
        document.getElementById("ldap-group-desc").value = "";
        fetchLdap();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteLdapGroup(groupName) {
    await fetch(`/api/ldap/groups/${groupName}`, { method: "DELETE" });
    fetchLdap();
}

// --- Group Membership Modal ---
async function manageMembers(groupName, activeMembers) {
    currentGroupForMembers = groupName;
    document.getElementById("modal-group-title").textContent = groupName;
    
    // Fetch all users to list them as checkboxes
    const res = await fetch("/api/ldap");
    const data = await res.json();
    
    const container = document.getElementById("modal-members-list");
    if (data.users.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-muted); font-size: 13px; padding: 10px;">Create LDAP users first before adding them to groups</p>';
    } else {
        container.innerHTML = data.users.map(usr => `
            <div style="display: flex; align-items: center; gap: 8px;">
                <input type="checkbox" value="${usr.username}" id="chk-mem-${usr.username}" style="width: auto; cursor: pointer;" ${activeMembers.includes(usr.username) ? "checked" : ""}>
                <label for="chk-mem-${usr.username}" style="margin: 0; cursor: pointer; color: var(--text-primary); font-size: 14px;">${usr.username}</label>
            </div>
        `).join("");
    }

    document.getElementById("modal-members").classList.add("active");
}

function closeMembersModal() {
    document.getElementById("modal-members").classList.remove("active");
    currentGroupForMembers = null;
}

async function saveGroupMembers() {
    if (!currentGroupForMembers) return;

    const checkboxes = document.querySelectorAll("#modal-members-list input[type='checkbox']");
    const usernames = [];
    checkboxes.forEach(chk => {
        if (chk.checked) usernames.push(chk.value);
    });

    const res = await fetch(`/api/ldap/groups/${currentGroupForMembers}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usernames })
    });

    if (res.ok) {
        closeMembersModal();
        fetchLdap();
    } else {
        const err = await res.json();
        alert(err.detail);
    }
}

// --- NTP Functions ---
async function fetchNtp() {
    try {
        const res = await fetch("/api/ntp");
        const data = await res.json();

        document.getElementById("ntp-pools").value = data.pools;

        // Render Tracking Stats
        const syncEl = document.getElementById("ntp-tracking-sync");
        if (data.stats.synchronized) {
            syncEl.textContent = "Synchronized";
            syncEl.style.color = "var(--success)";
        } else {
            syncEl.textContent = "Unsynchronized";
            syncEl.style.color = "var(--danger)";
        }

        document.getElementById("ntp-tracking-stratum").textContent = data.stats.stratum;
        document.getElementById("ntp-tracking-ref").textContent = data.stats.reference_id;

        // Render Upstream Sources Table
        const sourcesTbody = document.getElementById("ntp-sources-table");
        if (data.stats.sources.length === 0) {
            sourcesTbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No upstream sources found or NTP is disabled</td></tr>';
        } else {
            sourcesTbody.innerHTML = data.stats.sources.map(src => {
                let stateSymbol = src.state;
                let stateColor = "var(--text-secondary)";
                if (src.state === "*") {
                    stateSymbol = "✔"; // current best
                    stateColor = "var(--success)";
                } else if (src.state === "+") {
                    stateSymbol = "✚"; // candidate
                    stateColor = "var(--accent)";
                } else if (src.state === "?") {
                    stateSymbol = "❔"; // unreachable
                    stateColor = "var(--danger)";
                }
                return `
                    <tr>
                        <td style="text-align: center; color: ${stateColor}; font-weight: bold;">${stateSymbol}</td>
                        <td>${escapeHtml(src.name)}</td>
                        <td style="text-align: center;">${escapeHtml(src.stratum)}</td>
                        <td style="text-align: center;">${escapeHtml(src.last_rx)}</td>
                    </tr>
                `;
            }).join("");
        }
    } catch (err) {
        console.error("Error loading NTP details:", err);
    }
}

async function saveNtpSettings(e) {
    e.preventDefault();
    const pools = document.getElementById("ntp-pools").value.trim();
    const enabled = document.getElementById("toggle-ntp").checked;

    const res = await fetch("/api/ntp/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, pools })
    });
    if (res.ok) {
        alert("NTP settings saved successfully.");
        fetchNtp();
    } else {
        const err = await res.json();
        alert(err.detail || "Failed to update NTP settings.");
    }
}

// --- File Manager Functions ---
async function fetchFiles() {
    try {
        const res = await fetch("/api/files");
        const files = await res.json();

        const tbody = document.getElementById("files-list-table");
        if (files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No files found in shared directory yet</td></tr>';
            return;
        }

        tbody.innerHTML = files.map(file => {
            return `
                <tr>
                    <td style="font-weight: 500; font-family: monospace;">${escapeHtml(file.name)}</td>
                    <td style="text-align: center;">${formatBytes(file.size)}</td>
                    <td style="text-align: center; color: var(--text-secondary); font-size: 13px;">${escapeHtml(file.modified)}</td>
                    <td style="text-align: center;">
                        <a href="/api/files/download/${encodeURIComponent(file.name)}" class="btn btn-secondary btn-sm" style="padding: 4px 8px; margin-right: 6px;">Download</a>
                        <button class="btn btn-danger btn-sm" style="padding: 4px 8px;" onclick="deleteFileManagerFile('${escapeHtml(file.name)}')">&times;</button>
                    </td>
                </tr>
            `;
        }).join("");

        applyRoleRestrictions();

    } catch (err) {
        console.error("Error fetching files:", err);
    }
}

async function uploadFileManagerFile(e) {
    e.preventDefault();
    const fileField = document.getElementById("file-input-field");
    if (fileField.files.length === 0) return;

    const formData = new FormData();
    formData.append("file", fileField.files[0]);

    try {
        const res = await fetch("/api/files/upload", {
            method: "POST",
            body: formData
        });

        if (res.ok) {
            fileField.value = "";
            fetchFiles();
        } else {
            const err = await res.json();
            alert(err.detail || "Failed to upload file.");
        }
    } catch (err) {
        alert("Upload error.");
    }
}

async function deleteFileManagerFile(filename) {
    if (!confirm(`Are you sure you want to delete '${filename}'?`)) return;
    try {
        const res = await fetch(`/api/files/${encodeURIComponent(filename)}`, {
            method: "DELETE"
        });
        if (res.ok) {
            fetchFiles();
        } else {
            const err = await res.json();
            alert(err.detail || "Failed to delete file.");
        }
    } catch (err) {
        alert("Deletion error.");
    }
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// --- AAA Auth Logs Helper ---
async function fetchAuthLogs() {
    try {
        const res = await fetch("/api/logs/auth?limit=50");
        const logs = await res.json();

        const tbody = document.getElementById("radius-logs-table");
        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No authentication records found</td></tr>';
            return;
        }

        tbody.innerHTML = logs.map(log => {
            const statusClass = log.status === "Accepted" ? "status-indicator active" : "status-indicator inactive";
            const timeStr = log.timestamp.replace("T", " ").substring(0, 19);
            return `
                <tr>
                    <td><span style="font-size: 12px; color: var(--text-muted);">${timeStr}</span></td>
                    <td><span class="status-indicator active" style="padding: 2px 8px; font-size: 11px;">${log.service}</span></td>
                    <td><strong>${escapeHtml(log.username)}</strong></td>
                    <td><span style="font-family: monospace;">${escapeHtml(log.client_ip)}</span></td>
                    <td><span class="${statusClass}" style="padding: 2px 8px; font-size: 11px;">${log.status}</span></td>
                    <td><span style="font-size: 13px; color: var(--text-secondary);">${escapeHtml(log.message)}</span></td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error(e);
    }
}

async function clearAuthLogs() {
    if (!confirm("Clear AAA audit logs database?")) return;
    await fetch("/api/logs/auth/clear", { method: "POST" });
    fetchAuthLogs();
}

// --- Utils ---
function formatUptime(seconds) {
    const sec = parseInt(seconds, 10);
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);

    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// --- Network Interfaces Functions ---
let currentInterfacesList = [];

async function fetchNetworkInterfaces() {
    const tbody = document.getElementById("interfaces-table");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Loading network interfaces...</td></tr>';
    
    try {
        const res = await fetch("/api/network/interfaces");
        if (!res.ok) {
            const errorMsg = await parseResponseError(res, "Failed to load interfaces");
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--danger);">${escapeHtml(errorMsg)}</td></tr>`;
            return;
        }
        currentInterfacesList = await res.json();
        
        if (currentInterfacesList.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No network interfaces found.</td></tr>';
            return;
        }

        tbody.innerHTML = currentInterfacesList.map(iface => {
            const statusBadge = iface.is_up
                ? '<span class="status-indicator active"><div class="status-dot"></div>UP</span>'
                : '<span class="status-indicator inactive"><div class="status-dot"></div>DOWN</span>';

            const modeBadge = iface.mode === "dhcp"
                ? '<span class="badge badge-info">DHCP</span>'
                : '<span class="badge badge-secondary">Static</span>';

            const ipVal = iface.ip_address || iface.current_ip;
            const maskVal = iface.netmask || iface.current_netmask || "255.255.255.0";
            const ipStr = ipVal
                ? `<span style="font-family: monospace;">${escapeHtml(ipVal)} / ${escapeHtml(maskVal)}</span>`
                : '<span style="color: var(--text-muted); font-style: italic;">No IP assigned</span>';

            return `
                <tr>
                    <td><strong style="font-family: monospace; font-size: 14px;">${escapeHtml(iface.ifname)}</strong></td>
                    <td>${statusBadge}</td>
                    <td>${modeBadge}</td>
                    <td>${ipStr}</td>
                    <td>${escapeHtml(iface.gateway || "-")}</td>
                    <td><span style="font-family: monospace; font-size: 12px; color: var(--text-secondary);">${escapeHtml(iface.mac || "-")}</span></td>
                    <td style="text-align: center;">
                        <button class="btn btn-secondary btn-sm" style="padding: 4px 10px;" onclick="openInterfaceModal('${escapeHtml(iface.ifname)}')">Configure</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        console.error("Error fetching network interfaces:", err);
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--danger);">Failed to load interfaces.</td></tr>';
    }
}

function openInterfaceModal(ifname) {
    const iface = currentInterfacesList.find(i => i.ifname === ifname) || { ifname, mode: "static", is_up: true };

    document.getElementById("modal-iface-name").textContent = iface.ifname;
    document.getElementById("iface-name").value = iface.ifname;
    document.getElementById("iface-mode").value = iface.mode || "static";
    document.getElementById("iface-ip").value = iface.ip_address || iface.current_ip || "";
    document.getElementById("iface-netmask").value = iface.netmask || iface.current_netmask || "255.255.255.0";
    document.getElementById("iface-gateway").value = iface.gateway || "";
    document.getElementById("iface-dns").value = iface.dns_servers || "";
    document.getElementById("iface-is-up").checked = iface.is_up !== false;

    toggleIfaceModeFields();
    document.getElementById("modal-interface").classList.add("active");
}

function closeInterfaceModal() {
    document.getElementById("modal-interface").classList.remove("active");
}

function toggleIfaceModeFields() {
    const mode = document.getElementById("iface-mode").value;
    const staticFields = document.getElementById("iface-static-fields");
    if (staticFields) {
        staticFields.style.display = mode === "dhcp" ? "none" : "block";
    }
}

async function saveInterfaceConfig(e) {
    e.preventDefault();
    const ifname = document.getElementById("iface-name").value;
    const mode = document.getElementById("iface-mode").value;
    const ip_address = document.getElementById("iface-ip").value.trim();
    const netmask = document.getElementById("iface-netmask").value.trim();
    const gateway = document.getElementById("iface-gateway").value.trim();
    const dns_servers = document.getElementById("iface-dns").value.trim();
    const is_up = document.getElementById("iface-is-up").checked;

    try {
        const res = await fetch("/api/network/interfaces", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ifname, mode, ip_address, netmask, gateway, dns_servers, is_up })
        });
        if (res.ok) {
            closeInterfaceModal();
            fetchNetworkInterfaces();
            alert(`Interface ${ifname} configuration applied successfully.`);
        } else {
            const errorMsg = await parseResponseError(res, "Failed to apply interface settings");
            alert("Failed to apply interface settings: " + errorMsg);
        }
    } catch (err) {
        alert("Error saving interface config: " + err.message);
    }
}

// --- Backup & Config JSON Export/Import Functions ---
async function exportConfigBackup() {
    try {
        const response = await fetch("/api/backup/export");
        if (!response.ok) {
            throw new Error(await response.text() || "Failed to export backup");
        }
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `netlab_backup_${new Date().toISOString().split('T')[0]}.db`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        console.error("Backup export failed:", err);
        alert("Failed to export backup: " + err.message);
    }
}

async function exportConfigJson() {
    try {
        const response = await fetch("/api/config/export/json");
        if (!response.ok) throw new Error(await response.text() || "Export failed");
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `netlab_config_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        alert("Failed to export JSON config: " + err.message);
    }
}

async function importConfigAny(event) {
    event.preventDefault();
    if (!confirm("Are you sure you want to restore this configuration? Existing settings will be updated and active services will restart!")) {
        return;
    }
    const fileInput = document.getElementById("backup-file-input");
    if (!fileInput.files || fileInput.files.length === 0) {
        alert("Please select a backup file first.");
        return;
    }
    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("file", file);

    const isJson = file.name.endsWith(".json");
    const endpoint = isJson ? "/api/config/import/json" : "/api/backup/import";

    try {
        const response = await fetch(endpoint, {
            method: "POST",
            body: formData
        });
        if (!response.ok) {
            const errText = await response.text();
            let detail = "Import failed";
            try {
                const errJson = JSON.parse(errText);
                detail = errJson.detail || detail;
            } catch(e) {}
            throw new Error(detail);
        }
        alert("Configuration restored successfully! All services have been updated and restarted.");
        fetchStatus();
    } catch (err) {
        console.error("Configuration import failed:", err);
        alert("Failed to restore configuration: " + err.message);
    }
}

async function sendRadiusCoa(e) {
    e.preventDefault();
    const nas_ip = document.getElementById("coa-nas-ip").value.trim();
    const coa_port = parseInt(document.getElementById("coa-port").value) || 3799;
    const secret = document.getElementById("coa-secret").value.trim();
    const packet_type = document.getElementById("coa-type").value;
    const user_name = document.getElementById("coa-user").value.trim();
    const calling_station_id = document.getElementById("coa-mac").value.trim();
    const vlanVal = document.getElementById("coa-vlan").value.trim();
    const vlan_id = vlanVal ? parseInt(vlanVal) : null;
    const filter_id = document.getElementById("coa-filter").value.trim();

    try {
        const res = await fetch("/api/radius/coa/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nas_ip, coa_port, secret, packet_type, user_name, calling_station_id, vlan_id, filter_id })
        });

        if (!res.ok) throw new Error("Failed to send RADIUS CoA packet");
        const data = await res.json();

        const resultBox = document.getElementById("radius-coa-result");
        const titleEl = document.getElementById("coa-result-title");
        const badgeEl = document.getElementById("coa-result-badge");
        const detailsEl = document.getElementById("coa-result-details");

        resultBox.style.display = "block";

        if (data.status === "SUCCESS") {
            resultBox.style.borderColor = "#10b981";
            resultBox.style.background = "rgba(16, 185, 129, 0.08)";
            titleEl.style.color = "#10b981";
            titleEl.textContent = `✅ ${data.response_type.toUpperCase()} RECEIVED`;
            badgeEl.className = "badge badge-success";
            badgeEl.textContent = `ACK (${data.rtt_ms}ms)`;
        } else if (data.status === "REJECTED") {
            resultBox.style.borderColor = "#f59e0b";
            resultBox.style.background = "rgba(245, 158, 11, 0.08)";
            titleEl.style.color = "#f59e0b";
            titleEl.textContent = `⚠️ ${data.response_type.toUpperCase()} (NAK)`;
            badgeEl.className = "badge badge-warning";
            badgeEl.textContent = `NAK (${data.rtt_ms}ms)`;
        } else {
            resultBox.style.borderColor = "var(--danger)";
            resultBox.style.background = "rgba(239, 68, 68, 0.08)";
            titleEl.style.color = "var(--danger)";
            titleEl.textContent = `⛔ ${data.response_type.toUpperCase()}`;
            badgeEl.className = "badge badge-danger";
            badgeEl.textContent = data.status;
        }

        detailsEl.innerHTML = `
            <strong>Target NAS IP:</strong> ${escapeHtml(data.nas_ip)}:${data.port}<br>
            <strong>Packet Type Sent:</strong> ${escapeHtml(packet_type)}<br>
            <strong>Session Parameters:</strong> User-Name: <code>${escapeHtml(user_name || '-')}</code> | MAC: <code>${escapeHtml(calling_station_id || '-')}</code> | VLAN: <code>${vlan_id || '-'}</code> | Filter-Id: <code>${escapeHtml(filter_id || '-')}</code><br>
            <strong>Response Diagnostic:</strong> ${escapeHtml(data.message)}
        `;
    } catch (err) {
        alert("Error transmitting RADIUS CoA packet: " + err.message);
    }
}
