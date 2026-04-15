#!/bin/bash
# Quick start script for riks-context-engine sandbox

set -e

echo "=== Rik's Context Engine - Quick Start ==="

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker not found. Please install Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "ERROR: docker-compose not found. Please install docker-compose first."
    exit 1
fi

echo "Starting sandbox environment..."
docker-compose up --build -d

echo ""
echo "=== Sandbox running! ==="
echo "Container: riks-sandbox"
echo "Data dir: ./data (persistent)"
echo ""
echo "To exec into container:"
echo "  docker exec -it riks-sandbox bash"
echo ""
echo "To run tests:"
echo "  docker exec -it riks-sandbox pytest"
echo ""
echo "To stop:"
echo "  docker-compose down"