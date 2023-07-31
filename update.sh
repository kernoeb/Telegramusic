#!/usr/bin/env bash

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
