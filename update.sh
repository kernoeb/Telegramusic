#!/usr/bin/env bash

# Check if `token.env` file exists
if [ ! -f token.env ]; then
  echo "token.env file not found"
  exit 1
fi

source token.env

# Check for ENABLE_FLAC env variable
if [ "$ENABLE_FLAC" = "1" ]; then
  echo "FLAC is enabled"
else
  ENABLE_FLAC=0
  echo "FLAC is disabled"
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR" || exit 1

git pull || exit 1

# check if docker-compose or docker compose is installed
if [ -x "$(command -v docker-compose)" ]; then
  docker-compose up -d --build
elif [ -x "$(command -v docker)" ]; then
  docker compose up -d --build
else
  echo "docker-compose or docker is not installed"
  exit 1
fi
