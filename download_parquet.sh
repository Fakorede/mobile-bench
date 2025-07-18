#!/bin/bash

# Script to download all .parquet files from a remote server with authentication
# Usage: ./download_parquet.sh [local_destination_directory] [identity_file]

# Remote server details
REMOTE_USER="researchuser"
REMOTE_HOST="cse2327pc07u"
REMOTE_PATH="/home/researchuser/dev/MobileBench/data/android-test-automation/"

# Local destination directory (default is current directory if not specified)
LOCAL_DIR="${1:-.}"

# SSH identity file (private key) if provided as second argument
# If not provided, it will use default SSH keys or prompt for password
if [ -n "$2" ]; then
    IDENTITY_FILE="-i $2"
    echo "Using identity file: $2"
else
    IDENTITY_FILE=""
    echo "No identity file specified. Using default SSH configuration or password authentication."
fi

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Echo information about the transfer
echo "Downloading all .parquet files from ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH} to ${LOCAL_DIR}"

# Use scp with wildcard to download all .parquet files
# The -r option is for recursive download if there are subdirectories
# The -o StrictHostKeyChecking=no option skips the host key verification (optional, remove for more security)
# The -o BatchMode=no ensures that if key authentication fails, it will prompt for password
scp -r $IDENTITY_FILE -o BatchMode=no "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}*.parquet" "$LOCAL_DIR"

# Check if the download was successful
if [ $? -eq 0 ]; then
    echo "Download complete! All .parquet files have been saved to $LOCAL_DIR"
else
    echo "Error occurred during download. Please check your connection and try again."
    exit 1
fi