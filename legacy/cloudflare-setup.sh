#!/bin/bash
# Cloudflare Tunnel Setup Script for EC2
# Run this script on your EC2 instance (Amazon Linux 2023)

set -euo pipefail

APP_HEALTH_URL="${APP_HEALTH_URL:-http://localhost:8000/}"
APP_SERVICE_NAME="${APP_SERVICE_NAME:-kt-demo-alarm}"

echo "================================"
echo "Cloudflare Tunnel Setup"
echo "================================"
echo ""

# Step 1: Install cloudflared
echo "📦 Step 1: Installing cloudflared..."
if command -v cloudflared &> /dev/null; then
    echo "✅ cloudflared already installed: $(cloudflared --version)"
else
    wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
    sudo chmod +x /usr/local/bin/cloudflared
    echo "✅ cloudflared installed: $(cloudflared --version)"
fi
echo ""

# Step 2: Authenticate (requires manual browser interaction)
echo "🔐 Step 2: Authenticate with Cloudflare"
echo "⚠️  A browser window will open. Please log in to your Cloudflare account."
echo "⚠️  If the browser doesn't open automatically, copy the URL and paste it into your browser."
echo ""
read -p "Press Enter to continue with authentication..."
cloudflared tunnel login

if [ ! -f ~/.cloudflared/cert.pem ]; then
    echo "❌ Authentication failed. cert.pem not found."
    exit 1
fi
echo "✅ Authentication successful!"
echo ""

# Step 3: Create tunnel
echo "🔧 Step 3: Creating tunnel 'kt-demo-alarm-tunnel'..."
TUNNEL_OUTPUT=$(cloudflared tunnel create kt-demo-alarm-tunnel 2>&1 || true)
echo "$TUNNEL_OUTPUT"

# Extract Tunnel ID from output
TUNNEL_ID=$(echo "$TUNNEL_OUTPUT" | grep -oP '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)

if [ -z "$TUNNEL_ID" ]; then
    echo "⚠️  Could not extract Tunnel ID. Checking if tunnel already exists..."
    TUNNEL_ID=$(cloudflared tunnel list | grep kt-demo-alarm-tunnel | awk '{print $1}')

    if [ -z "$TUNNEL_ID" ]; then
        echo "❌ Failed to create or find tunnel."
        exit 1
    fi
fi

echo "✅ Tunnel ID: $TUNNEL_ID"
echo ""

# Step 4: Route DNS
echo "🌐 Step 4: Setting up DNS route..."
cloudflared tunnel route dns kt-demo-alarm-tunnel kt-demo-alarm || true
TUNNEL_HOSTNAME="kt-demo-alarm.trycloudflare.com"
echo "✅ Tunnel hostname: $TUNNEL_HOSTNAME"
echo ""

# Step 5: Create config file
echo "📝 Step 5: Creating configuration file..."
sudo mkdir -p /etc/cloudflared

sudo tee /etc/cloudflared/config.yml > /dev/null <<EOF
tunnel: $TUNNEL_ID
credentials-file: /home/ec2-user/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://localhost:8000

  - service: http_status:404
EOF

echo "✅ Configuration file created at /etc/cloudflared/config.yml"
echo ""

# Validate configuration
echo "🧪 Validating configuration..."
sudo cloudflared tunnel ingress validate
echo ""

# Step 6: Install and start systemd service
echo "🚀 Step 6: Installing systemd service..."
sudo cloudflared service install
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo ""
echo "⏳ Waiting for service to start..."
sleep 5

# Check service status
if sudo systemctl is-active --quiet cloudflared; then
    echo "✅ cloudflared service is running!"
else
    echo "⚠️  Service may not be running properly. Checking logs..."
    sudo journalctl -u cloudflared --no-pager | tail -20
fi
echo ""

# Step 7: Test the tunnel
echo "🧪 Step 7: Testing tunnel..."
echo "Testing local application first..."
if curl -fsS "${APP_HEALTH_URL}" > /dev/null 2>&1; then
    echo "✅ Local application is responding"
else
    echo "❌ Local application is not responding: ${APP_HEALTH_URL}"
    echo "Please check: systemctl status ${APP_SERVICE_NAME}"
    exit 1
fi

echo ""
echo "Testing HTTPS tunnel..."
sleep 3
if curl -fsS https://$TUNNEL_HOSTNAME/ > /dev/null 2>&1; then
    echo "✅ HTTPS tunnel is working!"
else
    echo "⚠️  HTTPS tunnel not responding yet. This may take a few minutes to propagate."
    echo "Try manually: curl https://$TUNNEL_HOSTNAME/"
fi
echo ""

# Summary
echo "================================"
echo "✅ Setup Complete!"
echo "================================"
echo ""
echo "Your HTTPS URLs:"
echo "  🔗 Health: https://$TUNNEL_HOSTNAME/"
echo "  🔗 Webhook: https://$TUNNEL_HOSTNAME/kakao/webhook/channel"
echo "  🔗 Chat: https://$TUNNEL_HOSTNAME/kakao/chat"
echo ""
echo "Next steps:"
echo "  1. Test the URLs above with curl"
echo "  2. Update Kakao Developer Console with these URLs"
echo "  3. Monitor logs: sudo journalctl -u cloudflared -f"
echo ""
echo "Service management:"
echo "  Status:  sudo systemctl status cloudflared"
echo "  Restart: sudo systemctl restart cloudflared"
echo "  Logs:    sudo journalctl -u cloudflared -f"
echo ""
