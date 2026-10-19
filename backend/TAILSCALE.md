# Molly + Tailscale Integration Guide

## Overview

Tailscale provides a zero-config VPN mesh that makes your server accessible **only to authorized devices** — no public ports, no firewall rules, no certificates. Perfect for Molly's mobile app connection.

```
┌─────────────┐     Tailnet (WireGuard)      ┌─────────────┐
│  Mobile     │ ◄─────────────────────────► │   Molly     │
│  App        │     Encrypted, authenticated │   server       │
│  (iOS/Android)│                              │  (Ubuntu)   │
└─────────────┘                              └─────────────┘
       │                                            │
       │  Molly API: https://molly.tailnet.ts.net  │
       │  WebSocket: wss://molly.tailnet.ts.net/ws │
       ▼                                            ▼
```

---

## Why Tailscale?

| Feature | Benefit for Molly |
|---------|-------------------|
| **Zero public exposure** | No port 8000 on public internet |
| **Device identity** | Each mobile device = unique Tailscale IP |
| **ACLs (Access Control Lists)** | Policy-as-code for who can reach Molly |
| **Key rotation** | Automatic WireGuard key rotation |
| **Mobile apps** | Official iOS/Android clients |
| **SSO integration** | GitHub/Google/Microsoft/Okta |
| **Audit logs** | Connection logs in admin console |
| **MagicDNS** | Human-readable names (`molly.tailnet.ts.net`) |

---

## Quick Start (5 minutes)

### 1. Install Tailscale on server

```bash
# On your Molly server (Ubuntu 22.04+)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Authenticate via the URL it prints
```

### 2. Configure Molly to Bind to Tailscale IP

```bash
# Get your Tailscale IP
tailscale ip -4
# Example output: 100.64.1.23

# Update .env
echo "HOST=100.64.1.23" >> /var/www/molly/backend/.env
# Or bind to all tailnet interfaces:
echo "HOST=0.0.0.0" >> /var/www/molly/backend/.env
# Then restrict with firewall (see below)
```

### 3. Restrict with UFW (Defense in Depth)

```bash
# Allow ONLY Tailscale interface
sudo ufw allow in on tailscale0 to any port 8000
sudo ufw deny 8000
sudo ufw enable

# Verify
sudo ufw status
# Should show:
# 8000/tcp  ALLOW  in on tailscale0
# 8000/tcp  DENY   Anywhere
```

### 4. Install Tailscale on Mobile

- **iOS**: App Store → "Tailscale"
- **Android**: Play Store → "Tailscale"
- Sign in with same account (GitHub/Google/Microsoft)

### 5. Test Connection

```bash
# From mobile (using Termius, or mobile browser)
curl http://100.64.1.23:8000/health
# {"status":"healthy","database":"ok","version":"1.0.0"}

# WebSocket test
wscat -c ws://100.64.1.23:8000/ws/conversations/test
```

---

## Production Hardening

### ACLs (Access Control Lists)

In Tailscale Admin Console → **Access Controls** → **Edit**:

```json
{
  "groups": {
    "group:admins": ["alice@company.com", "bob@company.com"],
    "group:operators": ["alice@company.com", "charlie@company.com"],
    "group:viewers": ["dave@company.com"]
  },
  "hosts": {
    "molly": "100.64.1.23"
  },
  "acls": [
    // Operators can reach Molly API
    {"action": "accept", "src": ["group:operators"], "dst": ["molly:8000"]},
    // Admins can reach everything on Molly server
    {"action": "accept", "src": ["group:admins"], "dst": ["molly:*"]},
    // Viewers read-only (if you add read-only endpoint)
    {"action": "accept", "src": ["group:viewers"], "dst": ["molly:8000"], "proto": "tcp", "ports": ["8000"]},
    // Deny all else
    {"action": "deny", "src": ["*"], "dst": ["*"]}
  ]
}
```

### MagicDNS (Human-Readable Names)

Admin Console → **DNS** → **MagicDNS** → Enable

```
# Now accessible as:
http://molly.tailnet-name.ts.net:8000/health
ws://molly.tailnet-name.ts.net:8000/ws/conversations/...
```

### Subnet Routers (Access server Services)

If Molly needs to reach other services on server (PostgreSQL, Redis):

```bash
# On server, advertise local subnet
sudo tailscale up --advertise-routes=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
# Approve in Admin Console → Machines → "..." → Edit route settings
```

---

## Mobile App Integration

### Connection Logic

```swift
// iOS (Swift) - Connection Manager
class MollyConnection {
    let baseURL = "http://molly.tailnet-name.ts.net:8000"  // MagicDNS
    // Or: "http://100.64.1.23:8000"  // Direct tailnet IP
    
    func connect() async throws {
        // 1. Verify Tailscale is running
        guard TailscaleAPI.isRunning else {
            throw MollyError.tailscaleNotRunning
        }
        
        // 2. Get tailnet IP (optional - for debugging)
        let tailnetIP = try await TailscaleAPI.localIP()
        print("Connected via Tailscale: \(tailnetIP)")
        
        // 3. Auth with Molly (device key flow)
        let deviceKey = try await Keychain.getDeviceKey()
        let challenge = try await registerDevice(pubkey: deviceKey.public)
        let tokens = try await verifyDevice(challenge: challenge, key: deviceKey)
        
        // 4. Connect WebSocket
        let wsURL = "ws://molly.tailnet-name.ts.net:8000/ws/conversations/\(conversationID)?token=\(tokens.access)"
        webSocket = WebSocket(url: wsURL)
        webSocket.connect()
    }
}
```

### Handling Network Changes

```swift
// Tailscale handles roaming automatically, but listen for reconnection
NotificationCenter.default.addObserver(
    forName: .tailscaleNetworkChanged,
    object: nil,
    queue: .main
) { _ in
    // Reconnect WebSocket if needed
    mollyConnection.reconnectIfNeeded()
}
```

### iOS Network Extension (Optional)

For always-on connection without user opening Tailscale app:

```xml
<!-- Info.plist -->
<key>NSExtension</key>
<dict>
    <key>NSExtensionPointIdentifier</key>
    <string>com.apple.networkextension</string>
    <key>NSExtensionPrincipalClass</key>
    <string>TailscaleNetworkExtension</string>
</dict>
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `curl: (7) Failed to connect` | Check `tailscale status` on both ends; verify UFW allows `tailscale0` |
| WebSocket disconnects | Tailscale roaming; implement auto-reconnect in mobile app |
| MagicDNS not resolving | Enable in Admin Console; flush DNS cache (`sudo dscacheutil -flushcache` on macOS) |
| Slow first connection | First WireGuard handshake; subsequent connections are instant |
| ACL changes not applying | Allow 30-60s for policy propagation |

### Debug Commands

```bash
# On server
tailscale status                    # Peer status
tailscale ping molly.tailnet.ts.net # Test connectivity
tailscale netcheck                  # Network diagnostics
sudo tailscale status --json        # Machine-readable

# Mobile (iOS Shortcuts / Android Termux)
tailscale status
tailscale ping 100.64.1.23
```

---

## Alternative: Cloudflare Tunnel (If Tailscale Not Viable)

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create molly

# Route traffic
cloudflared tunnel route dns molly molly.yourdomain.com

# Run as service
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

**Trade-offs:**
| Aspect | Tailscale | Cloudflare Tunnel |
|--------|-----------|-------------------|
| Public exposure | None | Yes (but WAF/DDoS protection) |
| Mobile access | Tailscale app required | Standard HTTPS |
| Device identity | Built-in | Need separate auth |
| Cost | Free (personal) | Free (with Cloudflare account) |

---

## Security Checklist

- [ ] Tailscale installed on server and all mobile devices
- [ ] Molly binds to `0.0.0.0:8000` but UFW restricts to `tailscale0`
- [ ] ACLs configured: only authorized users/groups can reach `:8000`
- [ ] MagicDNS enabled for human-readable hostname
- [ ] Mobile apps authenticate via the fleet gateway (real accounts + code-based pairing) - see top-level README
- [ ] WebSocket reconnection logic implemented
- [ ] Audit logs reviewed periodically (Admin Console → Audit Logs)
- [ ] Key rotation verified (automatic, but check `tailscale status`)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        TAILSCALE CONTROL PLANE                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Admin      │  │  DERP       │  │  Coordination│             │
│  │  Console    │  │  Relays     │  │  Server     │             │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  server     │   │  iOS     │   │ Android  │
        │  Molly   │   │  App     │   │  App     │
        │  100.64  │   │  100.92  │   │  100.101 │
        │  .1.23   │   │  .5.12   │   │  .3.45   │
        └────┬─────┘   └────┬─────┘   └────┬─────┘
             │              │              │
             │  WireGuard   │              │
             │  Mesh        │              │
             └──────────────┴──────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   Molly API       │
                    │  :8000 (HTTP)     │
                    │  /ws (WebSocket)  │
                    │  Auth: Device Key │
                    └───────────────────┘
```

---

## References

- [Tailscale Documentation](https://tailscale.com/kb/)
- [ACL Syntax](https://tailscale.com/kb/1018/acls)
- [MagicDNS](https://tailscale.com/kb/1081/magicdns)
- [Mobile Apps](https://tailscale.com/download)
- [API Reference](https://tailscale.com/api/)
- [Molly Auth API](./README.md#api-endpoints)