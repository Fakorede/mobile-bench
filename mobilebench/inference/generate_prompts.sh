#!/usr/bin/env bash
# Usage: ./run_evaluation_smart.sh
# ./run_evaluation_smart.sh --max-files 30 --disable-caching

set -e

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the project root two levels up from this script
PROJECT_ROOT="$SCRIPT_DIR/../.."


# Default values
MAX_FILES=20
FILE_SOURCE="oracle"
PROMPT_STYLE="style-3"
CACHE_DIR="$PROJECT_ROOT/cache/contexts"


# Parse command line arguments
ENABLE_SMART="--enable_smart_selection"
ENABLE_CACHING="--enable_caching"
ENABLE_CHUNKING="--chunk_large_contexts"

while [[ $# -gt 0 ]]; do
    case $1 in
        --disable-smart)
            ENABLE_SMART="--disable_smart_selection"
            shift
            ;;
        --disable-caching)
            ENABLE_CACHING="--disable_caching"
            shift
            ;;
        --disable-chunking)
            ENABLE_CHUNKING="--disable_chunking"
            shift
            ;;
        --max-files)
            MAX_FILES="$2"
            shift 2
            ;;
        --prompt-style)
            PROMPT_STYLE="$2"
            shift 2
            ;;
        --cache-dir)
            CACHE_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Smart evaluation prompt generation for Android projects"
            echo ""
            echo "OPTIONS:"
            echo "  --disable-smart      Disable smart file selection"
            echo "  --disable-caching    Disable context caching"
            echo "  --disable-chunking   Disable large context chunking"
            echo "  --max-files N        Maximum files to include (default: 20)"
            echo "  --prompt-style STYLE Prompt style (default: style-3)"
            echo "  --cache-dir DIR      Cache directory (default: PROJECT_ROOT/cache/contexts)"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Use all smart features"
            echo "  $0 --max-files 30                   # Include up to 30 files"
            echo "  $0 --disable-smart                  # Traditional oracle mode"
            echo "  $0 --disable-caching                # No caching"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Script to create evaluation prompts from task instances

# Get the directory where the script is located
# SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# # Set the project root two levels up from this script
# PROJECT_ROOT="$SCRIPT_DIR/../.."

# # Change to the inference directory
# cd "$SCRIPT_DIR"

# # Run the Python script with proper PYTHONPATH
# PYTHONPATH="$PROJECT_ROOT" python "$SCRIPT_DIR/create_evaluation_prompts.py" \
#     "$PROJECT_ROOT/data/tasks/" \
#     "$PROJECT_ROOT/data/prompts/" \
#     --prompt_style style-3 \
#     --file_source oracle \
#     "$@"

# echo "✅ Evaluation prompts creation complete!"
# echo "📁 Check $PROJECT_ROOT/data/prompts/ for results"



# Ensure required directories exist
mkdir -p "$PROJECT_ROOT/data/prompts"
mkdir -p "$CACHE_DIR"

# Print configuration
echo "🚀 Running enhanced evaluation prompt generation"
echo "📁 Project root: $PROJECT_ROOT"
echo "📊 Prompt style: $PROMPT_STYLE"
echo "📂 File source: $FILE_SOURCE"
echo "📄 Max files: $MAX_FILES"
echo "💾 Cache directory: $CACHE_DIR"

if [[ "$ENABLE_SMART" == "--enable_smart_selection" ]]; then
    echo "🧠 Smart file selection: ENABLED"
else
    echo "🧠 Smart file selection: DISABLED"
fi

if [[ "$ENABLE_CACHING" == "--enable_caching" ]]; then
    echo "🗄️  Context caching: ENABLED"
else
    echo "🗄️  Context caching: DISABLED"
fi

if [[ "$ENABLE_CHUNKING" == "--chunk_large_contexts" ]]; then
    echo "📝 Large context chunking: ENABLED"
else
    echo "📝 Large context chunking: DISABLED"
fi

echo ""

# Run the enhanced script
PYTHONPATH="$PROJECT_ROOT" python "$SCRIPT_DIR/create_evaluation_prompts.py" \
    "$PROJECT_ROOT/data/tasks/" \
    "$PROJECT_ROOT/data/prompts/" \
    --prompt_style "$PROMPT_STYLE" \
    --file_source "$FILE_SOURCE" \
    --max_files "$MAX_FILES" \
    --cache_dir "$CACHE_DIR" \
    "$ENABLE_SMART" \
    "$ENABLE_CACHING" \
    "$ENABLE_CHUNKING" \
    "$@"

echo ""
echo "✅ Evaluation prompt generation complete!"
echo "📊 Results saved to: $PROJECT_ROOT/data/prompts/"
echo "💾 Cache stored in: $CACHE_DIR"

# Show cache statistics if caching is enabled
if [[ "$ENABLE_CACHING" == "--enable_caching" ]] && [[ -d "$CACHE_DIR" ]]; then
    CACHE_COUNT=$(find "$CACHE_DIR" -name "*.pkl" | wc -l)
    echo "🗄️  Cache entries: $CACHE_COUNT"
fi