// Intercept global fetch to automatically add X-User-Role header for all API calls
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    if (url.toString().startsWith("/api/")) {
        options.headers = options.headers || {};
        options.headers["X-User-Role"] = sessionStorage.getItem("role") || "viewer";
    }
    return originalFetch(url, options);
};

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
    // Interval for live syslog streaming (if on dashboard or syslog view)
    setInterval(() => {
        if (sessionStorage.getItem("username")) fetchSyslogStream();
    }, 4000);
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
        "view-syslog": { t: "Syslog Logs Receiver", s: "Real-time syslog messages database collector" },
        "view-dns": { t: "Local DNS Settings", s: "Name resolution configuration and forwarding rules" },
        "view-dhcp": { t: "DHCP Server Pools", s: "Subnet scope configs and address reservations" },
        "view-radius": { t: "RADIUS Authentication", s: "Remote AAA authentication configuration" },
        "view-tacacs": { t: "TACACS+ Administration", s: "Command authorization and management access control" },
        "view-ldap": { t: "LDAP Directory Tree", s: "Centralized network directory management" },
        "view-ntp": { t: "NTP Time Synchronization", s: "Network Time Protocol daemon management" },
        "view-files": { t: "Shared File Manager", s: "Upload and download configurations via TFTP, FTP, and SFTP" }
    };

    if (titleMap[targetId]) {
        document.getElementById("page-header-title").textContent = titleMap[targetId].t;
        document.getElementById("page-header-subtitle").textContent = titleMap[targetId].s;
    }

    // Trigger tab-specific fetches
    if (targetId === "view-dns") fetchDns();
    if (targetId === "view-dhcp") fetchDhcp();
    if (targetId === "view-radius") fetchRadius();
    if (targetId === "view-tacacs") fetchTacacs();
    if (targetId === "view-ldap") fetchLdap();
    if (targetId === "view-ntp") fetchNtp();
    if (targetId === "view-files") fetchFiles();
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
            const err = await response.json();
            throw new Error(err.detail || "Failed to toggle service");
        }
        fetchStatus();
    } catch (error) {
        alert(error.message);
        toggle.checked = !isEnabled; // Revert switch UI state
    }
}

// --- Syslog Functions ---
let lastSyslogId = 0;
async function fetchSyslogStream() {
    // Only stream logs if dashboard or syslog tab is active
    const activeTab = document.querySelector(".view-panel.active").id;
    if (activeTab !== "view-dashboard" && activeTab !== "view-syslog") return;

    try {
        const response = await fetch("/api/syslog?limit=25");
        if (!response.ok) return;
        const data = await response.json();
        
        // Render into dashboard console box
        if (activeTab === "view-dashboard") {
            const dashboardConsole = document.getElementById("dashboard-syslog");
            renderConsoleLines(dashboardConsole, data.messages);
        } else if (activeTab === "view-syslog" && !document.getElementById("syslog-search").value) {
            // Only auto-update syslog viewer if search box is empty to prevent disrupting search
            const fullConsole = document.getElementById("syslog-console");
            renderConsoleLines(fullConsole, data.messages);
        }
    } catch (e) {
        console.error(e);
    }
}

async function fetchSyslogs() {
    const search = document.getElementById("syslog-search").value;
    const severity = document.getElementById("syslog-severity").value;
    const host = document.getElementById("syslog-host").value;

    let url = `/api/syslog?limit=150`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    if (severity) url += `&severity=${severity}`;
    if (host) url += `&hostname=${encodeURIComponent(host)}`;

    try {
        const response = await fetch(url);
        const data = await response.json();
        
        // Render console logs
        const fullConsole = document.getElementById("syslog-console");
        renderConsoleLines(fullConsole, data.messages);

        // Update hosts dropdown filter list
        const hostDropdown = document.getElementById("syslog-host");
        const selectedHost = hostDropdown.value;
        
        // Clear all except first
        hostDropdown.innerHTML = '<option value="">All Hosts</option>';
        data.hosts.forEach(h => {
            const opt = document.createElement("option");
            opt.value = h;
            opt.textContent = h;
            if (h === selectedHost) opt.selected = true;
            hostDropdown.appendChild(opt);
        });

    } catch (e) {
        console.error(e);
    }
}

function renderConsoleLines(container, messages) {
    if (!messages || messages.length === 0) {
        container.innerHTML = '<div class="console-line"><span class="console-msg">No messages found. Ensure Syslog Service is started and devices send to UDP 514.</span></div>';
        return;
    }

    const html = messages.map(msg => {
        const timeStr = msg.timestamp.split("T")[1].substring(0, 8);
        return `
            <div class="console-line sev-${msg.severity}">
                <span class="console-ts">[${timeStr}]</span>
                <span class="console-host">&lt;${msg.hostname}&gt;</span>
                <span class="console-msg">${escapeHtml(msg.message)}</span>
            </div>
        `;
    }).join("");

    container.innerHTML = html;
}

async function clearLogs(type) {
    if (type === "syslog") {
        if (!confirm("Are you sure you want to clear all syslog messages from the database?")) return;
        await fetch("/api/syslog/clear", { method: "POST" });
        fetchSyslogs();
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
        const err = await res.json();
        alert(err.detail);
    }
}

async function deleteDnsRecord(hostname) {
    await fetch(`/api/dns/records/${hostname}`, { method: "DELETE" });
    fetchDns();
}

// --- DHCP Functions ---
async function fetchDhcp() {
    const res = await fetch("/api/dhcp");
    const data = await res.json();

    document.getElementById("dhcp-interface").value = data.interface;
    document.getElementById("dhcp-lease").value = data.lease_time;
    document.getElementById("dhcp-start").value = data.start;
    document.getElementById("dhcp-end").value = data.end;
    document.getElementById("dhcp-netmask").value = data.netmask;
    document.getElementById("dhcp-gateway").value = data.gateway;
    document.getElementById("dhcp-dns").value = data.dns_servers;

    // Render static leases pool
    const staticTbody = document.getElementById("dhcp-static-table");
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

    // Render active leases
    const activeTbody = document.getElementById("dhcp-leases-table");
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

async function saveDhcpSettings(e) {
    e.preventDefault();
    const interface = document.getElementById("dhcp-interface").value;
    const lease_time = document.getElementById("dhcp-lease").value;
    const start = document.getElementById("dhcp-start").value;
    const end = document.getElementById("dhcp-end").value;
    const netmask = document.getElementById("dhcp-netmask").value;
    const gateway = document.getElementById("dhcp-gateway").value;
    const dns_servers = document.getElementById("dhcp-dns").value;
    const enabled = document.getElementById("toggle-dhcp").checked;

    await fetch("/api/dhcp/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, interface, start, end, netmask, gateway, dns_servers, lease_time })
    });
    alert("DHCP settings applied.");
    fetchDhcp();
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
                <td>${escapeHtml(usr.username)}</td>
                <td><span style="font-family: monospace;">${escapeHtml(usr.password)}</span></td>
                <td><span class="status-indicator active" style="padding: 2px 8px; font-size: 11px;">Privilege ${usr.privilege}</span></td>
                <td><button class="btn btn-danger btn-sm" onclick="deleteTacacsUser('${usr.username}')">&times;</button></td>
            </tr>
        `).join("");
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

    const res = await fetch("/api/tacacs/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, privilege })
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
