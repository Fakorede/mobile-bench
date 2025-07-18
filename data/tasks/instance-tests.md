



Please help me with a python script that takes a jsonl file containing data in the following format

```bash
{
    "instance_id": "bitwarden__android-4914",
    "repo": "bitwarden/android",
    "pull_number": 4914,
    "base_commit": "22376bfe4b...",  # Buggy version
    "patch": "...",                   # The actual code fix
    "test_patch": "...",             # Test changes (if any)
    "problem_statement": "PM-8953: Require 4 digits for pin entry\n## Objective\nThis PR updates the Pin Entry dialog to require 4 digits minimum when creating a new pin.",
    "hints_text": "",
    "created_at": "2025-03-25T19:55:53Z"
}
```

The script should do the following:

- setup a clean environment (repo and docker container)
- for each instance, checkout and test the base commit
- cleanup all build and test results/caches
- test the gold patch (apply the patch and test_patch)
- generate expectations by comparison and store in dataset i.e. 
```
    fail_to_pass = [
        test for test in base_results 
        if base_results[test] == 'FAILED' and gold_results[test] == 'PASSED'
    ]
    pass_to_pass = [
        test for test in base_results
        if base_results[test] == 'PASSED' and gold_results[test] == 'PASSED'  
    ]
    
    # 5. Store in dataset
    return {
        'FAIL_TO_PASS': fail_to_pass,
        'PASS_TO_PASS': pass_to_pass,
    }
```
- cleanup before moving to the next instance and clear all build and test files and cache


Note:
- use mingc/android-build-box docker image (only pull image if it doesnt already exist)
- dynamically detect what versions of java, gradle to use


example shell script

 Function to determine compatible Java version based on Gradle version
# Limited to available Java versions: 8, 11, 17, and 21
# Usage: determine_java_version "gradle_version" "has_kotlin"
determine_java_version() {
  local gradle_version="$1"
  local has_kotlin="${2:-false}"  # Optional second parameter indicating Kotlin usage
  # Initialize with the default version (will be used if version detection fails)
  local java_version="$DEFAULT_JAVA_VERSION"
  
  # Ensure DEFAULT_JAVA_VERSION is one of the available versions (8, 11, 17, 21)
  case "$DEFAULT_JAVA_VERSION" in
    8|11|17|21) 
      # Default Java version is available, use it as fallback
      ;;
    *)
      # If default is not available, set to a safe default
      java_version="17"
      echo "Warning: Default Java version $DEFAULT_JAVA_VERSION is not available. Using Java 17 as fallback." >&2
      ;;
  esac
  
  echo "Detected Gradle version: $gradle_version" >&2
  
  # Extract major.minor version (e.g., 7.0.2 -> 7.0)
  local gradle_major_minor=$(echo "$gradle_version" | grep -oE '^[0-9]+\.[0-9]+')
  
  # Gradle-Java compatibility mapping with only available versions (8, 11, 17, 21)
  # Reference: https://docs.gradle.org/current/userguide/compatibility.html
  if [[ -z "$gradle_major_minor" ]]; then
    echo "Could not parse Gradle version, using default Java version: $java_version" >&2
  # Gradle < 5.0 works best with Java 8
  elif (( $(echo "$gradle_major_minor < 5.0" | bc -l) )); then
    java_version="8"
    echo "For Gradle $gradle_major_minor, using Java 8" >&2
  # Gradle 5.0 to 6.8 works best with Java 11
  elif (( $(echo "$gradle_major_minor < 6.9" | bc -l) )); then
    java_version="11"
    echo "For Gradle $gradle_major_minor, using Java 11" >&2
  # Gradle 6.9 to 7.4 works best with Java 17
  elif (( $(echo "$gradle_major_minor < 7.5" | bc -l) )); then
    java_version="17"
    echo "For Gradle $gradle_major_minor, using Java 17" >&2
  # Gradle 7.5+ works with Java 21
  else
    java_version="21"
    echo "For Gradle $gradle_major_minor, using Java 21" >&2
  fi
  
  # Special case: Kotlin compilation issues with Java 17+ on older Gradle versions
  # If Kotlin is being used, prefer Java 11 for Gradle < 7.3
  if [ "$has_kotlin" = "true" ] && (( $(echo "$gradle_major_minor < 7.3" | bc -l) )); then
    if [ "$java_version" = "17" ] || [ "$java_version" = "21" ]; then
      echo "Kotlin detected with Gradle $gradle_major_minor - downgrading from Java $java_version to Java 11 for better compatibility" >&2
      java_version="11"
    fi
  fi
  
  # Make sure the selected Java version is one of the available versions (8, 11, 17, 21)
  # If not, pick the closest available lower version
  case "$java_version" in
    8|11|17|21) 
      # Java version is available, do nothing
      ;;
    *)
      # If we somehow got a different version, find the closest available lower version
      if (( java_version > 21 )); then
        java_version="21"
      elif (( java_version > 17 )); then
        java_version="17"
      elif (( java_version > 11 )); then
        java_version="11"
      else
        java_version="8"
      fi
      echo "Selected Java version not available, falling back to Java $java_version" >&2
      ;;
  esac
  
  # Only return the version number as the function result
  echo "$java_version"
}

# Function to detect if a project uses Kotlin
# Usage: detect_kotlin_usage
detect_kotlin_usage() {
  if grep -q "kotlin" build.gradle 2>/dev/null || 
     grep -q "kotlin" app/build.gradle 2>/dev/null || 
     grep -q "kotlin" */build.gradle 2>/dev/null || 
     grep -q "kotlin" buildSrc/build.gradle.kts 2>/dev/null || 
     [ -d "buildSrc/src/main/kotlin" ] || 
     find . -name "*.kt" -o -name "*.kts" | grep -q . ; then
    echo "true"
    echo "Kotlin detected in project" >&2
  else
    echo "false"
  fi
}

# Function to detect Gradle version from a project
# Usage: detect_gradle_version
detect_gradle_version() {
  local gradle_version=""
  
  # First try to get version from properties file if it exists
  if [ -f './gradle/wrapper/gradle-wrapper.properties' ]; then
    local gradle_version_from_props=$(grep -o 'gradle-[0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?-' ./gradle/wrapper/gradle-wrapper.properties | grep -o '[0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?')
    
    if [ -n "$gradle_version_from_props" ]; then
      gradle_version="$gradle_version_from_props"
      echo "Gradle version detected from properties file: $gradle_version" >&2
    fi
  fi
  
  # If we couldn't get version from properties, try running gradlew
  if [ -z "$gradle_version" ] && [ -f './gradlew' ]; then
    chmod +x ./gradlew
    
    # Try to get Gradle version (look for the specific "Gradle X.Y.Z" line)
    gradle_version=$(./gradlew --version 2>/dev/null | grep -E '^Gradle [0-9]+\.[0-9]+(\.[0-9]+)?$' | head -n 1 | awk '{print $2}')
    
    # If that doesn't work, try a more general approach
    if [ -z "$gradle_version" ]; then
      gradle_version=$(./gradlew --version 2>/dev/null | grep -o 'Gradle [0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?' | head -n 1 | awk '{print $2}')
    fi
    
    if [ -n "$gradle_version" ]; then
      echo "Gradle version detected from gradlew command: $gradle_version" >&2
    fi
  fi
  
  # Return the detected version or empty string if not found
  echo "$gradle_version"
}

# Function to run tests for a specific commit
# Usage: run_android_tests "repo_dir" "commit_sha" "timeout_seconds" "label"
run_android_tests() {
  local repo_dir="$1"
  local commit_sha="$2"
  local timeout_seconds="$3"
  local label="$4"
  local script_dir="$PWD"
  local test_result=""
  
  echo "=== Testing $label: $commit_sha ==="
  cd "$repo_dir"
  git checkout "$commit_sha"
  git submodule update --init --recursive
  
  # Detect Gradle version
  local gradle_version=""
  if [ -f './gradlew' ]; then
    echo "=== Detecting Gradle version for $label ==="
    gradle_version=$(detect_gradle_version)
  fi
  
  # Detect if project uses Kotlin
  local has_kotlin="false"
  if [ -f './gradlew' ]; then
    has_kotlin=$(detect_kotlin_usage)
  fi
  
  # Determine Java version
  local java_version="$DEFAULT_JAVA_VERSION"
  if [ -n "$gradle_version" ]; then
    java_version=$(determine_java_version "$gradle_version" "$has_kotlin")
    echo "Using Java version $java_version for Gradle $gradle_version"
  else
    echo "Failed to detect Gradle version, using default Java version: $java_version"
  fi
  
  # Run tests on the commit with real-time output
  echo "=== Running tests on $label with Java $java_version ==="
  docker run --rm \
    --network host \
    --dns 8.8.8.8 \
    --dns 8.8.4.4 \
    -v "$script_dir/$repo_dir":/project mingc/android-build-box bash -c "
    cd /project && 
    echo '=== Container environment ready ===' && 
    echo '=== Setting Java version to $java_version ===' && 

    # Initialize jenv if available
    if command -v jenv &> /dev/null; then
      eval \"\$(jenv init -)\"
      
      # List available versions for debugging
      echo 'Available Java versions in jenv:'
      jenv versions || echo 'Failed to list jenv versions'
      
      # Set specific Java version from script parameter
      jenv global $java_version || jenv global ${java_version}.0 || echo 'Failed to set Java version with jenv, trying alternatives'
      
      echo 'Current Java version after jenv:'
      java -version 2>&1
    fi
    
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
      
      # Run tests with timeout (allow failure)
      timeout $timeout_seconds ./gradlew test || true
    else
      # If gradlew doesn't exist but build.gradle does, use system gradle
      if [ -f './build.gradle' ] || [ -f './app/build.gradle' ]; then
        timeout $timeout_seconds gradle test || true
      else
        echo 'No Gradle build files found'
      fi
    fi
  "
  
...
}

## Usage


```shell
# Basic usage
python android_test_runner.py input.jsonl output.jsonlpython android_test_runner.py /home/thefabdev/dev/mobile-bench/data/tasks/Bitwarden_instances.jsonl /home/thefabdev/dev/mobile-bench/data/tasks/Bitwarden_tested_instances.jsonl

# With custom timeout (default: 10 minutes)
python android_test_runner.py \
/home/thefabdev/dev/mobile-bench/data/tasks/Bitwarden_task_instances.jsonl \
/home/thefabdev/dev/mobile-bench/data/tasks/Bitwarden_tested_instances.jsonl \
15

```




