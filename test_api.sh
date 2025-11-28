#!/bin/bash

# Test script for Zylch API endpoints
# Usage: ./test_api.sh

API_URL="http://localhost:8000"

echo "🧪 Testing Zylch AI HTTP API"
echo "============================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test function
test_endpoint() {
    local name=$1
    local method=$2
    local endpoint=$3
    local data=$4

    echo -n "Testing $name... "

    if [ "$method" == "GET" ]; then
        response=$(curl -s "$API_URL$endpoint")
    else
        response=$(curl -s -X $method "$API_URL$endpoint" \
            -H "Content-Type: application/json" \
            -d "$data")
    fi

    if [ $? -eq 0 ] && echo "$response" | grep -q -v "error"; then
        echo -e "${GREEN}✓ OK${NC}"
        echo "   Response: $(echo $response | head -c 100)..."
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        echo "   Error: $response"
        return 1
    fi
    echo ""
}

# Check if server is running
echo "Checking if API server is running..."
if ! curl -s "$API_URL/health" > /dev/null; then
    echo -e "${RED}❌ API server not running!${NC}"
    echo ""
    echo "Start the server with:"
    echo "  cd /Users/mal/starchat/zylch"
    echo "  ./venv/bin/uvicorn zylch.api.main:app --reload"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ Server is running${NC}"
echo ""

# Test Health Check
echo "=== Health Check ==="
test_endpoint "Health" "GET" "/health"
echo ""

# Test Skills List
echo "=== Skills API ==="
test_endpoint "List Skills" "GET" "/api/skills/list"
echo ""

# Test Gaps Summary (may fail if no cache)
echo "=== Gaps API ==="
test_endpoint "Gaps Summary" "GET" "/api/gaps/summary"
echo ""

# Test Pattern Stats
echo "=== Patterns API ==="
test_endpoint "Pattern Stats" "GET" "/api/patterns/stats"
echo ""

# Test Skill Classification (requires API key)
echo "=== Skill Classification (requires ANTHROPIC_API_KEY) ==="
test_endpoint "Classify Intent" "POST" "/api/skills/classify" \
    '{"user_input": "Find emails from Luisa about the invoice"}'
echo ""

echo "============================"
echo "✅ API testing complete!"
echo ""
echo "Full documentation: http://localhost:8000/docs"
