#!/bin/bash

# Script to automate cloning and testing Android GitHub repos in a container (https://github.com/mingchen/docker-android-build-box)
# Usage: ./script.sh [csv_filename] [timeout_minutes] [java_version]
# Example: ./script.sh repo_tests.csv 10 17
# Note: If [java_version] is provided, it will override auto-detection
#
# Exit on error - but with our improved error handling
set -o pipefail

# Use the current directory where the script is saved
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$SCRIPT_DIR"

# Set timeout in minutes (default: 10 minutes)
TIMEOUT_MINUTES="${2:-10}"
TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))

# Set Java version (default: 17, but will be auto-detected if not provided)
FORCE_JAVA_VERSION="${3:-}"

# Default CSV filename or use provided argument
CSV_FILE="${1:-repo_tests.csv}"

# Check if CSV file exists
if [ ! -f "$CSV_FILE" ]; then
  echo "Error: CSV file '$CSV_FILE' not found in $(pwd)"
  exit 1
fi

# Check if parse_android_tests.sh exists
if [ ! -f "parse_android_tests.sh" ]; then
  echo "Error: parse_android_tests.sh not found in $(pwd)"
  exit 1
fi

# Make parse script executable
chmod +x parse_android_tests.sh

# Create a temporary file for storing updated results
TEMP_CSV="${CSV_FILE}.tmp"
# Copy header line to temp file
head -n 1 "$CSV_FILE" > "$TEMP_CSV"

echo "=== Starting Android repo test automation ==="
echo "Reading repositories from: $CSV_FILE"
if [ -n "$FORCE_JAVA_VERSION" ]; then
  echo "Force using Java version: $FORCE_JAVA_VERSION (will override auto-detection)"
else
  echo "Java version will be auto-detected from each repository"
fi

# Log file for errors
ERROR_LOG="test_automation_errors.log"
touch "$ERROR_LOG"

# Function to detect Java version from project files
detect_java_version() {
  local project_dir="$1"
  local detected_version=""
  
  # Check for Java version in gradle.properties
  if [ -f "$project_dir/gradle.properties" ]; then
    # Look for org.gradle.java.home or sourceCompatibility or targetCompatibility
    local java_prop=$(grep -E 'org\.gradle\.java\.home.*jdk|org\.gradle\.java\.home.*jvm' "$project_dir/gradle.properties" | head -1)
    if [ -n "$java_prop" ]; then
      # Extract version number (assuming format contains something like jdk8, jdk11, java8, java11)
      detected_version=$(echo "$java_prop" | grep -oE '[0-9]+' | head -1)
    else
      # Check for JavaVersion.VERSION_XX
      local java_ver=$(grep -E 'JavaVersion\.VERSION_[0-9]+|JavaVersion\.VERSION_[0-9]+_[0-9]+' "$project_dir/gradle.properties" | head -1)
      if [ -n "$java_ver" ]; then
        detected_version=$(echo "$java_ver" | grep -oE '[0-9]+(_[0-9]+)?' | head -1 | tr '_' '.')
      fi
    fi
  fi
  
  # Check build.gradle files if version not found yet
  if [ -z "$detected_version" ]; then
    # Find all build.gradle files (including build.gradle.kts)
    local gradle_files=$(find "$project_dir" -name "build.gradle" -o -name "build.gradle.kts" | grep -v "buildSrc")
    
    for gradle_file in $gradle_files; do
      # Check for sourceCompatibility, targetCompatibility, JavaVersion.VERSION_XX
      local compat=$(grep -E 'sourceCompatibility|targetCompatibility|compileJava.sourceCompatibility|JavaVersion\.VERSION_' "$gradle_file" | head -1)
      
      if [ -n "$compat" ]; then
        # Try to extract the Java version number
        if echo "$compat" | grep -q "1\."; then
          # Handle old style '1.8' format
          detected_version=$(echo "$compat" | grep -oE '1\.[0-9]+' | sed 's/1\.//' | head -1)
        elif echo "$compat" | grep -q "VERSION_"; then
          # Handle JavaVersion.VERSION_1_8 or JavaVersion.VERSION_11
          if echo "$compat" | grep -q "VERSION_1_"; then
            detected_version=$(echo "$compat" | grep -oE '1_[0-9]+' | sed 's/1_//' | head -1)
          else
            detected_version=$(echo "$compat" | grep -oE 'VERSION_[0-9]+' | sed 's/VERSION_//' | head -1)
          fi
        else
          # Direct version specification
          detected_version=$(echo "$compat" | grep -oE '[0-9]+(\.[0-9]+)?' | head -1 | cut -d '.' -f 1)
        fi
        
        if [ -n "$detected_version" ]; then
          break
        fi
      fi
    done
  fi
  
  # Check for .java-version file (used by jenv)
  if [ -z "$detected_version" ] && [ -f "$project_dir/.java-version" ]; then
    detected_version=$(cat "$project_dir/.java-version" | tr -d '[:space:]')
    # If it contains something like '11.0', extract just '11'
    detected_version=$(echo "$detected_version" | cut -d '.' -f 1)
  fi
  
  # Check for .sdkmanrc file
  if [ -z "$detected_version" ] && [ -f "$project_dir/.sdkmanrc" ]; then
    local sdk_java=$(grep -E 'java=' "$project_dir/.sdkmanrc" | head -1)
    if [ -n "$sdk_java" ]; then
      # Extract version number (often looks like java=11.0.12-open)
      detected_version=$(echo "$sdk_java" | grep -oE '[0-9]+' | head -1)
    fi
  fi
  
  # Default to 8 for old projects (if no explicit version found)
  # This is an assumption, as many pre-Android 7.0 projects used Java 8
  if [ -z "$detected_version" ]; then
    # Look for compileSdkVersion to determine Android API level
    local sdk_version=$(grep -E 'compileSdkVersion' $(find "$project_dir" -name "*.gradle" -o -name "*.gradle.kts" | head -10) 2>/dev/null | head -1 | grep -oE '[0-9]+')
    
    if [ -n "$sdk_version" ] && [ "$sdk_version" -lt 26 ]; then
      # Older Android projects (pre-Oreo) likely use Java 8
      detected_version="8"
    elif [ -n "$sdk_version" ] && [ "$sdk_version" -lt 30 ]; then
      # Android 8-10 often use Java 8 or 11
      detected_version="11"
    else
      # Newer Android projects typically use Java 11 or 17
      detected_version="17"
    fi
  fi
  
  echo "$detected_version"
}

# Skip header row and process each line in the CSV
tail -n +2 "$CSV_FILE" | while IFS=, read -r repo_full_name pr_number sha filename status additions deletions changes blob_url raw_url contents_url merge_commit_sha head_ref head_sha head_repo_full_name base_ref base_sha fail_to_pass pass_to_pass;
do
  # Format the repo name as organizationname__reponame
  REPO_NAME=$(echo "$repo_full_name" | sed 's/\//__/')

  echo "=== Processing repository: $repo_full_name ==="
  
  # Format GitHub URL
  REPO_URL="https://github.com/${repo_full_name}.git"
  
  # Clone the repository if it doesn't exist
  if [ ! -d "$REPO_NAME" ]; then
    echo "=== Cloning repository with submodules ==="
    if ! git clone --recursive "$REPO_URL" "$REPO_NAME"; then
      echo "ERROR: Failed to clone repository $repo_full_name" | tee -a "$ERROR_LOG"
      echo "$repo_full_name,$pr_number,$sha,$filename,$status,$additions,$deletions,$changes,$blob_url,$raw_url,$contents_url,$merge_commit_sha,$head_ref,$head_sha,$head_repo_full_name,$base_ref,$base_sha,Failed to clone repository,Failed to clone repository" >> "$TEMP_CSV"
      continue
    fi
  else
    echo "=== Repository already exists, fetching latest changes and updating submodules ==="
    cd "$REPO_NAME"
    if ! git fetch --all; then
      echo "ERROR: Failed to fetch updates for repository $repo_full_name" | tee -a "$ERROR_LOG"
      cd "$SCRIPT_DIR"
      echo "$repo_full_name,$pr_number,$sha,$filename,$status,$additions,$deletions,$changes,$blob_url,$raw_url,$contents_url,$merge_commit_sha,$head_ref,$head_sha,$head_repo_full_name,$base_ref,$base_sha,Failed to fetch updates,Failed to fetch updates" >> "$TEMP_CSV"
      continue
    fi
    git submodule update --init --recursive || echo "Warning: Submodule update failed, continuing anyway"
    cd "$SCRIPT_DIR"
  fi
  
  # Initialize test result variables
  MERGE_COMMIT_TEST_RESULT=""
  BASE_SHA_TEST_RESULT=""

  # Process base SHA
  echo "=== Testing base commit: $base_sha ==="
  cd "$REPO_NAME"
  
  # Check if the base_sha exists
  if ! git cat-file -e "$base_sha^{commit}" 2>/dev/null; then
    echo "ERROR: Base commit $base_sha does not exist in repository $repo_full_name" | tee -a "$SCRIPT_DIR/$ERROR_LOG"
    BASE_SHA_TEST_RESULT="Error: Base commit hash not found"
  else
    # Try to checkout the base commit
    git reset --hard HEAD || echo "Warning: Failed to reset to HEAD"
    git clean -fdx || echo "Warning: Failed to clean untracked files"
    if ! git checkout -f "$base_sha"; then
      echo "ERROR: Failed to checkout base commit $base_sha in repository $repo_full_name" | tee -a "$SCRIPT_DIR/$ERROR_LOG"
      BASE_SHA_TEST_RESULT="Error: Failed to checkout base commit"
    else
      # Update submodules (but don't fail if they can't be updated)
      git submodule update --init --recursive || echo "Warning: Submodule update failed, continuing anyway"
      
      # Detect Java version or use forced version
      if [ -n "$FORCE_JAVA_VERSION" ]; then
        JAVA_VERSION="$FORCE_JAVA_VERSION"
        echo "=== Using forced Java version: $JAVA_VERSION ==="
      else
        JAVA_VERSION=$(detect_java_version "$(pwd)")
        echo "=== Detected Java version: $JAVA_VERSION ==="
      fi
      
      # If still empty, default to Java 17
      if [ -z "$JAVA_VERSION" ]; then
        JAVA_VERSION="17"
        echo "=== No Java version detected, defaulting to: $JAVA_VERSION ==="
      fi
      
      # Run tests on base SHA with real-time output
      echo "=== Running tests on base SHA with Java $JAVA_VERSION ==="
      docker run --rm \
        --network host \
        --dns 8.8.8.8 \
        --dns 8.8.4.4 \
        -v "$SCRIPT_DIR/$REPO_NAME":/project mingc/android-build-box bash -c "
        cd /project && 
        echo '=== Container environment ready ===' && 
        echo '=== Setting Java version to $JAVA_VERSION ===' && 

        # Initialize jenv if available
        if command -v jenv &> /dev/null; then
          eval \"\$(jenv init -)\"
          
          # Try different version formats with jenv
          jenv global $JAVA_VERSION || jenv global ${JAVA_VERSION}.0 || 
          jenv global 1.${JAVA_VERSION} || jenv global openjdk64-${JAVA_VERSION} || 
          jenv global openjdk-${JAVA_VERSION} || echo 'Failed to set exact Java version with jenv, trying alternatives'
          
          echo 'Current Java version after jenv:'
          java -version 2>&1
        fi
        
        # If jenv failed or is not available, try JAVA_HOME and alternatives
        if [ -d '/usr/lib/jvm/java-${JAVA_VERSION}-openjdk' ]; then
          export JAVA_HOME='/usr/lib/jvm/java-${JAVA_VERSION}-openjdk'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /usr/lib/jvm/java-${JAVA_VERSION}-openjdk'
        elif [ -d '/usr/lib/jvm/java-${JAVA_VERSION}-oracle' ]; then
          export JAVA_HOME='/usr/lib/jvm/java-${JAVA_VERSION}-oracle'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /usr/lib/jvm/java-${JAVA_VERSION}-oracle'
        elif [ -d '/opt/java/${JAVA_VERSION}' ]; then
          export JAVA_HOME='/opt/java/${JAVA_VERSION}'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /opt/java/${JAVA_VERSION}'
        fi
        
        echo 'Current Java version:'
        java -version 2>&1
        
        # Set ANDROID_SDK_ROOT if needed
        if [ -d '/opt/android-sdk' ]; then
          export ANDROID_SDK_ROOT='/opt/android-sdk'
          echo 'Set ANDROID_SDK_ROOT to /opt/android-sdk'
        fi

        echo '=== Running Gradle tests ===' && 

        rm -rf ~/.gradle/caches/
        
        # Check if Gradle wrapper exists
        if [ -f './gradlew' ]; then
          # Make gradlew executable
          chmod +x ./gradlew

          ./gradlew clean
          
          # Run tests with timeout (allow failure)
          timeout $TIMEOUT_SECONDS ./gradlew test || true
        else
          # If gradlew doesn't exist but build.gradle does, use system gradle
          if [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
            timeout $TIMEOUT_SECONDS gradle test || true
          else
            echo 'No Gradle build files found'
          fi
        fi
      "
      
      # Parse test results for base SHA
      echo "=== Parsing test results for base SHA ==="
      TEMP_RESULT_FILE=$(mktemp)
      # Run the parser script and capture the output
      "$SCRIPT_DIR/parse_android_tests.sh" "$SCRIPT_DIR/$REPO_NAME" > "$TEMP_RESULT_FILE" 2>&1
      
      # Check if any test files were found
      if grep -q "No Android test result XML files found" "$TEMP_RESULT_FILE"; then
        BASE_SHA_TEST_RESULT="Gradle build failed and test couldn't run: $base_sha"
      else
        # Store the full test results output (excluding the summary section)
        # Replace commas with semicolons and keep the original format
        # Use a tab character as the separator
        BASE_SHA_TEST_RESULT=$(sed '/OVERALL SUMMARY/,$d' "$TEMP_RESULT_FILE" | 
                               grep -v "=== " | 
                               grep -v "Searching for" | 
                               grep -v "^Found " |
                               sed 's/,/;/g' |
                               sed 's/$/\t/' |  # Add tab at end of each line
                               tr -d '\n')      # Remove newlines
        
        # Remove the trailing tab if present
        BASE_SHA_TEST_RESULT=$(echo "$BASE_SHA_TEST_RESULT" | sed 's/\t$//')
      fi
      
      # Clean up temp file
      rm -f "$TEMP_RESULT_FILE"
      
      # Run Gradle clean to clear build files after testing
      echo "=== Cleaning up Gradle build files after testing base SHA ==="
      docker run --rm \
        -v "$SCRIPT_DIR/$REPO_NAME":/project mingc/android-build-box bash -c "
        cd /project && 
        if [ -f './gradlew' ]; then
          chmod +x ./gradlew
          ./gradlew clean || true
        elif [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
          gradle clean || true
        fi
        # Remove test reports since we've already processed them
        find . -path '*/build/test-results/*' -type d -exec rm -rf {} + 2>/dev/null || true
        find . -path '*/build/reports/tests/*' -type d -exec rm -rf {} + 2>/dev/null || true
        "
    fi
  fi
  
  # Process merge commit
  echo "=== Testing merge commit: $merge_commit_sha ==="
  
  # Check if the merge_commit_sha exists
  if ! git cat-file -e "$merge_commit_sha^{commit}" 2>/dev/null; then
    echo "ERROR: Commit $merge_commit_sha does not exist in repository $repo_full_name" | tee -a "$SCRIPT_DIR/$ERROR_LOG"
    MERGE_COMMIT_TEST_RESULT="Error: Commit hash not found"
  else
    # Try to checkout the commit
    git reset --hard HEAD || echo "Warning: Failed to reset to HEAD"
    git clean -fdx || echo "Warning: Failed to clean untracked files"
    if ! git checkout -f "$merge_commit_sha"; then
      echo "ERROR: Failed to checkout commit $merge_commit_sha in repository $repo_full_name" | tee -a "$SCRIPT_DIR/$ERROR_LOG"
      MERGE_COMMIT_TEST_RESULT="Error: Failed to checkout commit"
    else
      # Update submodules (but don't fail if they can't be updated)
      git submodule update --init --recursive || echo "Warning: Submodule update failed, continuing anyway"
      
      # Detect Java version or use forced version
      # We need to detect again since base might have different requirements than merge commit
      if [ -n "$FORCE_JAVA_VERSION" ]; then
        JAVA_VERSION="$FORCE_JAVA_VERSION"
        echo "=== Using forced Java version: $JAVA_VERSION ==="
      else
        JAVA_VERSION=$(detect_java_version "$(pwd)")
        echo "=== Detected Java version: $JAVA_VERSION ==="
      fi
      
      # If still empty, default to Java 17
      if [ -z "$JAVA_VERSION" ]; then
        JAVA_VERSION="17"
        echo "=== No Java version detected, defaulting to: $JAVA_VERSION ==="
      fi
      
      # Run tests on merge commit - show output in real-time
      echo "=== Running tests on merge commit with Java $JAVA_VERSION ==="
      docker run --rm \
        --network host \
        --dns 8.8.8.8 \
        --dns 8.8.4.4 \
        -v "$SCRIPT_DIR/$REPO_NAME":/project mingc/android-build-box bash -c "
        cd /project && 
        echo '=== Container environment ready ===' && 
        echo '=== Setting Java version to $JAVA_VERSION ===' && 

        # Initialize jenv if available
        if command -v jenv &> /dev/null; then
          eval \"\$(jenv init -)\"
          
          # Try different version formats with jenv
          jenv global $JAVA_VERSION || jenv global ${JAVA_VERSION}.0 || 
          jenv global 1.${JAVA_VERSION} || jenv global openjdk64-${JAVA_VERSION} || 
          jenv global openjdk-${JAVA_VERSION} || echo 'Failed to set exact Java version with jenv, trying alternatives'
          
          echo 'Current Java version after jenv:'
          java -version 2>&1
        fi
        
        # If jenv failed or is not available, try JAVA_HOME and alternatives
        if [ -d '/usr/lib/jvm/java-${JAVA_VERSION}-openjdk' ]; then
          export JAVA_HOME='/usr/lib/jvm/java-${JAVA_VERSION}-openjdk'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /usr/lib/jvm/java-${JAVA_VERSION}-openjdk'
        elif [ -d '/usr/lib/jvm/java-${JAVA_VERSION}-oracle' ]; then
          export JAVA_HOME='/usr/lib/jvm/java-${JAVA_VERSION}-oracle'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /usr/lib/jvm/java-${JAVA_VERSION}-oracle'
        elif [ -d '/opt/java/${JAVA_VERSION}' ]; then
          export JAVA_HOME='/opt/java/${JAVA_VERSION}'
          export PATH=\"\$JAVA_HOME/bin:\$PATH\"
          echo 'Set JAVA_HOME to /opt/java/${JAVA_VERSION}'
        fi
        
        echo 'Current Java version:'
        java -version 2>&1
        
        # Set ANDROID_SDK_ROOT if needed
        if [ -d '/opt/android-sdk' ]; then
          export ANDROID_SDK_ROOT='/opt/android-sdk'
          echo 'Set ANDROID_SDK_ROOT to /opt/android-sdk'
        fi

        echo '=== Running Gradle tests ===' && 

        rm -rf ~/.gradle/caches/
        
        # Check if Gradle wrapper exists
        if [ -f './gradlew' ]; then
          # Make gradlew executable
          chmod +x ./gradlew

          ./gradlew clean
          
          # Run tests with timeout (allow failure)
          timeout $TIMEOUT_SECONDS ./gradlew test || true
        else
          # If gradlew doesn't exist but build.gradle does, use system gradle
          if [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
            timeout $TIMEOUT_SECONDS gradle test || true
          else
            echo 'No Gradle build files found'
          fi
        fi
      "
      
      # Parse test results for merge commit
      echo "=== Parsing test results for merge commit ==="
      TEMP_RESULT_FILE=$(mktemp)
      # Run the parser script and capture the output
      "$SCRIPT_DIR/parse_android_tests.sh" "$SCRIPT_DIR/$REPO_NAME" > "$TEMP_RESULT_FILE" 2>&1
      
      # Check if any test files were found
      if grep -q "No Android test result XML files found" "$TEMP_RESULT_FILE"; then
        MERGE_COMMIT_TEST_RESULT="Gradle build failed and test couldn't run: $merge_commit_sha"
      else
        # Store the full test results output (excluding the summary section)
        # Replace commas with semicolons and keep the original format
        # Use a tab character as the separator
        MERGE_COMMIT_TEST_RESULT=$(sed '/OVERALL SUMMARY/,$d' "$TEMP_RESULT_FILE" | 
                                   grep -v "=== " | 
                                   grep -v "Searching for" | 
                                   grep -v "^Found " |
                                   sed 's/,/;/g' |
                                   sed 's/$/\t/' |  # Add tab at end of each line
                                   tr -d '\n')      # Remove newlines
        
        # Remove the trailing tab if present
        MERGE_COMMIT_TEST_RESULT=$(echo "$MERGE_COMMIT_TEST_RESULT" | sed 's/\t$//')
      fi
      
      # Clean up temp file
      rm -f "$TEMP_RESULT_FILE"
      
      # Run Gradle clean to clear build files after testing
      echo "=== Cleaning up Gradle build files after testing merge commit ==="
      docker run --rm \
        -v "$SCRIPT_DIR/$REPO_NAME":/project mingc/android-build-box bash -c "
        cd /project && 
        if [ -f './gradlew' ]; then
          chmod +x ./gradlew
          ./gradlew clean || true
        elif [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
          gradle clean || true
        fi
        # Remove test reports since we've already processed them
        find . -path '*/build/test-results/*' -type d -exec rm -rf {} + 2>/dev/null || true
        find . -path '*/build/reports/tests/*' -type d -exec rm -rf {} + 2>/dev/null || true"
    fi
  fi
  
  
  # Go back to script directory
  cd "$SCRIPT_DIR"
  
  # Update results in CSV
  echo "=== Updating test results ==="
  echo "Merge commit test result: $MERGE_COMMIT_TEST_RESULT"
  echo "Base SHA test result: $BASE_SHA_TEST_RESULT"
  
  # Append the updated line to the temp CSV file
  echo "$repo_full_name,$pr_number,$sha,$filename,$status,$additions,$deletions,$changes,$blob_url,$raw_url,$contents_url,$merge_commit_sha,$head_ref,$head_sha,$head_repo_full_name,$base_ref,$base_sha,$BASE_SHA_TEST_RESULT,$MERGE_COMMIT_TEST_RESULT" >> "$TEMP_CSV"
  
  echo "=== Completed testing for $repo_full_name ==="
  echo "================================================"
done

OUTPUT_FILE="repo_tests_results.csv"
mv "$TEMP_CSV" "$OUTPUT_FILE"

echo "=== All testing completed ==="
echo "Results saved to $OUTPUT_FILE"
echo "Error log saved to $ERROR_LOG"