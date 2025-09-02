#!/usr/bin/env bash

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the project root two levels up from this script
PROJECT_ROOT="$SCRIPT_DIR/../.."

# Run the Python script with proper PYTHONPATH
PYTHONPATH="$PROJECT_ROOT" python "$SCRIPT_DIR/collect_github_data.py" \
    --repos duckduckgo/Android \
    --path_prs "$PROJECT_ROOT/data/prs" \
    --path_tasks "$PROJECT_ROOT/data/tasks" \
    --cutoff_date 20230101
# duckduckgo/Android