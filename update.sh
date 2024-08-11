#!/usr/bin/env bash

# Ensure the script is run from the directory where it is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR" || exit 1

# Pull the latest changes from the repository
git pull || exit 1

# Check if `token.env` file exists
if [ ! -f token.env ]; then
  echo "token.env file not found"
  exit 1
fi

# Load environment variables from `token.env` file and export them
set -a
source token.env
set +a

# Check for ENABLE_FLAC env variable
if [ "$ENABLE_FLAC" = "1" ]; then
  echo "FLAC is enabled"
else
  export ENABLE_FLAC="0"
  echo "FLAC is disabled"
fi

# Check if docker compose is available
if docker compose version &>/dev/null; then
  docker compose up -d --build
# Fall back to docker-compose if docker compose is not available
elif command -v docker-compose &>/dev/null; then
  docker-compose up -d --build
else
  echo "Neither docker compose nor docker-compose is available"
  exit 1
fi