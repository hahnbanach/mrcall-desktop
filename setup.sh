#!/bin/bash
# Setup script for MrPark

set -e

echo "🏗️  Setting up MrPark..."

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
required_version="3.11"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python 3.11+ required (found $python_version)"
    exit 1
fi

echo "✅ Python $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --upgrade pip > /dev/null

# Install dependencies
echo "📦 Installing dependencies..."
pip install -e . > /dev/null

echo "✅ Dependencies installed"

# Check .env file
if [ ! -f ".env" ]; then
    echo "⚠️  No .env file found, copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your API keys"
fi

# Create directories
mkdir -p credentials cache data

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env with your API keys"
echo "2. Set up Gmail OAuth credentials: https://developers.google.com/gmail/api/quickstart/python"
echo "3. Place credentials in: credentials/gmail_oauth.json"
echo "4. Run: source venv/bin/activate"
echo "5. Run: python -m mrpark.cli.main"
