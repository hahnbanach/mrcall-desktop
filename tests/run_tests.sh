#!/bin/bash

# Test runner script for Von Neumann flow tests
# Usage: ./tests/run_tests.sh [integration|e2e|all]

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Zylch Von Neumann Flow Test Suite ===${NC}\n"

# Check if pytest is installed
if ! python -m pytest --version &> /dev/null; then
    echo -e "${RED}Error: pytest not installed${NC}"
    echo "Install with: pip install pytest pytest-asyncio"
    exit 1
fi

# Check Supabase configuration
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_ROLE_KEY" ]; then
    echo -e "${RED}Warning: Supabase not configured${NC}"
    echo "Set environment variables:"
    echo "  export SUPABASE_URL='your-url'"
    echo "  export SUPABASE_SERVICE_ROLE_KEY='your-key'"
    echo ""
    echo "Tests will be skipped if Supabase is not configured."
    echo ""
fi

# Determine what to run
TEST_TYPE=${1:-all}

case $TEST_TYPE in
    integration)
        echo -e "${BLUE}Running integration tests...${NC}\n"
        python -m pytest tests/integration/test_von_neumann_flow.py -v
        ;;
    e2e)
        echo -e "${BLUE}Running E2E tests...${NC}\n"
        python -m pytest tests/e2e/test_sync.py -v
        ;;
    all)
        echo -e "${BLUE}Running all tests...${NC}\n"
        python -m pytest tests/integration/test_von_neumann_flow.py tests/e2e/test_sync.py -v
        ;;
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo "Usage: $0 [integration|e2e|all]"
        exit 1
        ;;
esac

# Check exit code
if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}✓ All tests passed!${NC}"
else
    echo -e "\n${RED}✗ Some tests failed${NC}"
    exit 1
fi
