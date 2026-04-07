#!/bin/bash

# A sample only deployment script to deploy to /opt from a git checkout in your home dir on a server or mini pc server

# --- Configuration ---
APP_NAME="ticktap-wiki"
SOURCE_DIR="$HOME/other_git/ticktap_wiki"
DEST_DIR="/opt/ticktap_wiki"
SERVICE_NAME="ticktap-wiki.service"

echo "🚀 Starting deployment for $APP_NAME..."

# 1. Sync files to /opt (Excluding the local venv and git)
echo "🔄 Syncing files to $DEST_DIR..."
sudo rsync -av --delete \
    --exclude=".git/" \
    --exclude=".venv/" \
    --exclude="__pycache__/" \
    --exclude="deploy.sh" \
    "$SOURCE_DIR/" "$DEST_DIR/"

# 2. Setup/Update Virtual Environment
echo "🐍 Ensuring virtual environment exists..."
if [ ! -d "$DEST_DIR/.venv" ]; then
    sudo python3 -m venv "$DEST_DIR/.venv"
fi

# 3. Install Requirements
echo "📥 Installing dependencies..."
sudo "$DEST_DIR/.venv/bin/pip" install -r "$DEST_DIR/requirements.txt"

# 4. Permissions
echo "🔐 Setting permissions for www-data..."
sudo chown -R www-data:www-data "$DEST_DIR"

# 5. Restart Service
echo "♻️  Restarting $SERVICE_NAME..."
sudo systemctl restart "$SERVICE_NAME"

echo "✅ Deployment complete! Checking logs..."
sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
