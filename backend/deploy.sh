#!/bin/bash
# Molly Backend Deployment Script for Ubuntu
#
# This worker only ever talks to its fleet gateway now (see
# app/auth/dependencies.py - the old self-hosted, directly-reachable
# mode is gone). It makes one outbound connection out to the gateway;
# nothing needs to be exposed publicly for it to work. There's no nginx
# or public port here - if you separately want this box reachable
# directly (e.g. over Tailscale, for SSH/`molly run`), that's a network
# concern to set up on its own, not something this script does.

set -e

MOLLY_USER="molly"
MOLLY_DIR="/var/www/molly"
MOLLY_BACKEND_DIR="$MOLLY_DIR/backend"

echo "=== Molly Backend Deployment ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# This script installs a PRE-BUILT Nuitka binary - it doesn't compile it.
# Build it first (on a machine matching the target OS/arch) with:
#   ./build_nuitka.sh
# which produces dist/cli.dist/. Point this script at that directory:
BUILD_DIST_DIR="${1:-$(dirname "$0")/dist/cli.dist}"
if [ ! -x "$BUILD_DIST_DIR/molly" ]; then
    echo "No compiled build found at $BUILD_DIST_DIR/molly"
    echo "Run ./build_nuitka.sh first, or pass the dist dir as an argument:"
    echo "  sudo ./deploy.sh /path/to/cli.dist"
    exit 1
fi

# Install the few system tools deploy needs (no python3/pip/venv at
# runtime anymore; the compiled binary is self-contained)
echo "Installing system dependencies..."
apt-get update
apt-get install -y git rsync

# Create molly user
if ! id "$MOLLY_USER" &>/dev/null; then
    echo "Creating user: $MOLLY_USER"
    useradd -r -s /bin/bash -d "$MOLLY_DIR" "$MOLLY_USER"
fi

# Create directories. The backend resolves data paths relative to its
# WorkingDirectory (the backend dir), so credentials, SQLite, projects, and
# uploads all live under backend/data/ - not a sibling of backend/.
echo "Creating directories..."
mkdir -p "$MOLLY_BACKEND_DIR"
mkdir -p "$MOLLY_BACKEND_DIR/data/projects"
mkdir -p "$MOLLY_BACKEND_DIR/data/uploads"
mkdir -p "$MOLLY_BACKEND_DIR/data/skills"
mkdir -p "$MOLLY_DIR/logs"

# Copy the compiled standalone build into place. This replaces whatever
# was here before (old venv-based deploys included) - the runtime dir is
# now just "the compiled directory plus .env plus data/".
echo "Installing compiled backend..."
rsync -a --delete --exclude='.env' --exclude='data' --exclude='logs' \
    "$BUILD_DIST_DIR/" "$MOLLY_BACKEND_DIR/"

# Set ownership
chown -R "$MOLLY_USER:$MOLLY_USER" "$MOLLY_DIR"

# Make `molly connect` / `molly worker ...` usable from any directory.
# The CLI resolves .env and data/ relative to the working directory, so the
# wrapper enters the deployment directory before exec'ing the binary.
cat > /usr/local/bin/molly <<'MOLLY_WRAPPER'
#!/bin/sh
cd /var/www/molly/backend || exit 1
exec ./molly "$@"
MOLLY_WRAPPER
chmod 0755 /usr/local/bin/molly

# Create .env if not exists
if [ ! -f "$MOLLY_BACKEND_DIR/.env" ]; then
    echo "Creating .env from example..."
    cp "$MOLLY_BACKEND_DIR/.env.example" "$MOLLY_BACKEND_DIR/.env" 2>/dev/null || touch "$MOLLY_BACKEND_DIR/.env"
    echo "IMPORTANT: Edit $MOLLY_BACKEND_DIR/.env with your API key!"
fi

# No separate DB init step needed: init_db()/create_default_projects()
# run automatically in app/main.py's lifespan hook (loaded by `molly serve`) on every startup,
# including the first one below.

# Install systemd service
echo "Installing systemd service..."
cat > /etc/systemd/system/molly.service <<EOF
[Unit]
Description=Molly Backend - Autonomous DevOps Assistant
After=network.target

[Service]
Type=exec
User=$MOLLY_USER
Group=$MOLLY_USER
WorkingDirectory=$MOLLY_BACKEND_DIR
ExecStart=$MOLLY_BACKEND_DIR/molly serve
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=$MOLLY_BACKEND_DIR/data $MOLLY_DIR/logs

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable molly

# Start service
echo "Starting Molly service..."
systemctl start molly
sleep 2
systemctl status molly --no-pager

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit $MOLLY_BACKEND_DIR/.env with your LLM API key, then:"
echo "   systemctl restart molly"
echo "2. Enroll this worker with the fleet gateway (required - this worker"
echo "   won't accept any authenticated request until it is). The gateway"
echo "   URL is baked in via settings.gateway_http_url, so this only needs"
echo "   a token:"
echo "     sudo -u $MOLLY_USER molly worker enroll --token <enrollment_token>"
echo "   Get <enrollment_token> from the gateway admin:"
echo "     curl -X POST https://your-gateway.example.com/admin/workers/tokens \\"
echo "       -H \"X-API-Key: <your_tenant_api_key>\""
echo "3. Restart once more so it picks up the saved credential:"
echo "   systemctl restart molly"
echo "4. Pair a device from the Molly app:"
echo "   sudo -u $MOLLY_USER molly connect"
echo "5. Check logs: journalctl -u molly -f"
