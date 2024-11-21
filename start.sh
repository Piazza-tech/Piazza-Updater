#!/bin/bash

# Load environment variables from .env file
set -a
source .env
set +a

# List of external volumes to check and create if needed
VOLUMES=("weaviate_data" "updater" "ollama")
# Name of the tunnel network to check
NETWORKS=""

# Function to create a volume if it does not exist
create_volume_if_not_exists() {
  local volume_name=$1
  if ! docker volume ls | grep -q "$volume_name"; then
    echo "Creating external volume '$volume_name'..."
    docker volume create "$volume_name"
  fi
}

# Function to create a network if it does not exist
create_network_if_not_exists() {
  local network_name=$1
  if ! docker network ls | grep -q "$network_name"; then
    echo "Creating network '$network_name'..."
    docker network create "$network_name"
  fi
}

# Loop through each volume in the list and create if it doesn't exist
for volume in "${VOLUMES[@]}"; do
  create_volume_if_not_exists "$volume"
done

# Check for tunnel network and create if it doesn't exist
create_network_if_not_exists "$NETWORKS"

# Check if PRODUCTION is set to False
if [ "$PRODUCTION" == "False" ]; then
    echo "Testing with small docker-compose-s.yml ..."
    docker compose --env-file .env -f docker-compose-s.yml up --build
else
    echo "Deploying with docker-compose.yml ..."
    docker compose --env-file .env -f docker-compose.yml up -d --build
fi