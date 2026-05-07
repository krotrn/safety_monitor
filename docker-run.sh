#!/bin/bash

# SafeGrid Docker Helper Script

COMMAND=$1
PROFILE=$2

if [ -z "$COMMAND" ] || [ -z "$PROFILE" ]; then
    echo "Usage: ./docker-run.sh [up|down|build] [dev|prod]"
    exit 1
fi

if [[ "$PROFILE" != "dev" && "$PROFILE" != "prod" ]]; then
    echo "Profile must be 'dev' or 'prod'"
    exit 1
fi

docker compose --profile $PROFILE $COMMAND
