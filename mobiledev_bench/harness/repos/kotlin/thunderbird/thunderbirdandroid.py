import re
from typing import Optional, Union
import textwrap
from mobiledev_bench.harness.image import Config, File, Image
from mobiledev_bench.harness.instance import Instance
from mobiledev_bench.harness.pull_request import PullRequest
from mobiledev_bench.harness.test_result import TestResult


class ThunderbirdAndroidImageBase(Image):
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> Union[str, "Image"]:
        return "mingc/android-build-box:1.29.0"

    def image_tag(self) -> str:
        return "base"

    def workdir(self) -> str:
        return "base"

    def files(self) -> list[File]:
        return [
            File(
                ".",
                "detect_jdk.sh",
                """#!/bin/bash
# Detect required JDK version for project
REPO_DIR="$1"
BASE_SHA="$2"

cd "$REPO_DIR" || exit 1

# Try to checkout the base SHA
if ! git checkout "$BASE_SHA" 2>/dev/null; then
    echo "17"  # Default to 17 if checkout fails
    exit 0
fi

# Check for Kotlin JVM target in build files
JVM_TARGET=$(find . -name "build.gradle.kts" -o -name "build.gradle" 2>/dev/null | xargs grep -oP 'jvmTarget\\s*=\\s*"\\K[0-9]+|jvmToolchain\\s*\\{\\s*languageVersion\\.set\\(JavaLanguageVersion\\.of\\(\\K[0-9]+' 2>/dev/null | head -1)

# Check libs.versions.toml for JDK version
if [ -f "gradle/libs.versions.toml" ]; then
    TOML_JVM=$(grep -oP 'jvmTarget\\s*=\\s*"\\K[0-9]+|jdk\\s*=\\s*"\\K[0-9]+' gradle/libs.versions.toml 2>/dev/null | head -1)
    [ -n "$TOML_JVM" ] && JVM_TARGET="$TOML_JVM"
fi

# Determine required JDK
if [ -n "$JVM_TARGET" ]; then
    REQUIRED_JDK="$JVM_TARGET"
else
    REQUIRED_JDK=17  # Default to 17
fi

# Validate JDK is available in base image
case "$REQUIRED_JDK" in
    8|11|17|21)
        echo "$REQUIRED_JDK"
        ;;
    *)
        echo "17"  # Default to 17 for unsupported versions
        ;;
esac

# Reset git state
git reset --hard HEAD >/dev/null 2>&1 || true
""",
            ),
        ]

    def dockerfile(self) -> str:
        image_name = self.dependency()
        if isinstance(image_name, Image):
            image_name = image_name.image_full_name()

        if self.config.need_clone:
            code = f"RUN git clone https://github.com/{self.pr.org}/{self.pr.repo}.git /home/{self.pr.repo}"
        else:
            code = f"COPY {self.pr.repo} /home/{self.pr.repo}"

        # JDK detection and configuration using jenv
        jdk_setup = f"""
COPY detect_jdk.sh /tmp/detect_jdk.sh
RUN chmod +x /tmp/detect_jdk.sh && \\
    /tmp/detect_jdk.sh /home/{self.pr.repo} {self.pr.base.sha} > /opt/jenv/version && \\
    echo "Set JDK version to: $$(cat /opt/jenv/version)" && \\
    echo "Verifying JDK configuration:" && \\
    java -version
"""

        return f"""FROM {image_name}
USER root
{self.global_env}

WORKDIR /home/
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

{code}

{jdk_setup}

{self.clear_env}

"""


class ThunderbirdAndroidImageDefault(Image):
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> Image | None:
        return ThunderbirdAndroidImageBase(self.pr, self._config)

    def image_tag(self) -> str:
        return f"pr-{self.pr.number}"

    def workdir(self) -> str:
        return f"pr-{self.pr.number}"

    def files(self) -> list[File]:
        return [
            File(
                ".",
                "fix.patch",
                f"{self.pr.fix_patch}",
            ),
            File(
                ".",
                "test.patch",
                f"{self.pr.test_patch}",
            ),
            File(
                ".",
                "check_git_changes.sh",
                """#!/bin/bash
set -e

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "check_git_changes: Not inside a git repository"
  exit 1
fi

if [[ -n $(git status --porcelain) ]]; then
  echo "check_git_changes: Uncommitted changes"
  exit 1
fi

echo "check_git_changes: No uncommitted changes"
exit 0

""".format(),
            ),
            File(
                ".",
                "prepare.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
git reset --hard
bash /home/check_git_changes.sh
git checkout {pr.base.sha}
bash /home/check_git_changes.sh
chmod +x gradlew

# Set up Gradle user home
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p $GRADLE_USER_HOME

# Configure Gradle for Thunderbird
cat > $GRADLE_USER_HOME/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Running base tests ==="
{test_cmd} --no-daemon --stacktrace --continue --parallel || true

echo "=== Collecting test results ==="
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
""".format(pr=self.pr, test_cmd=self.pr.test_command or "./gradlew clean test --max-workers 8"),
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
chmod +x gradlew

# Set up Gradle user home
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p $GRADLE_USER_HOME

# Configure Gradle for Thunderbird
cat > $GRADLE_USER_HOME/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Running tests ==="
{test_cmd} --no-daemon --stacktrace --continue --parallel || true

echo "=== Collecting test results ==="
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
""".format(pr=self.pr, test_cmd=self.pr.test_command or "./gradlew clean test --max-workers 8"),
            ),
            File(
                ".",
                "test-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}

# Apply test patch with multiple strategies
echo "=== Applying test patch ==="
if git apply --verbose /home/test.patch 2>&1; then
    echo "SUCCESS: git apply worked"
elif git apply --verbose --ignore-space-change --ignore-whitespace /home/test.patch 2>&1; then
    echo "SUCCESS: git apply with whitespace options worked"
elif patch --batch --fuzz=3 -p1 < /home/test.patch 2>&1; then
    echo "SUCCESS: patch with fuzz worked"
else
    echo "ERROR: All patch strategies failed"
    exit 1
fi

chmod +x gradlew

# Set up Gradle user home
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p $GRADLE_USER_HOME

# Configure Gradle for Thunderbird
cat > $GRADLE_USER_HOME/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Cleaning build artifacts ==="
./gradlew clean --no-daemon || true

echo "=== Running test patch tests ==="
{test_cmd} --no-daemon --stacktrace --continue --parallel || true

echo "=== Collecting test results ==="
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
""".format(pr=self.pr, test_cmd=self.pr.test_command or "./gradlew clean test --max-workers 8"),
            ),
            File(
                ".",
                "fix-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}

# Apply test patch with multiple strategies
echo "=== Applying test patch ==="
if git apply --verbose /home/test.patch 2>&1; then
    echo "SUCCESS: git apply worked for test patch"
elif git apply --verbose --ignore-space-change --ignore-whitespace /home/test.patch 2>&1; then
    echo "SUCCESS: git apply with whitespace options worked for test patch"
elif patch --batch --fuzz=3 -p1 < /home/test.patch 2>&1; then
    echo "SUCCESS: patch with fuzz worked for test patch"
else
    echo "ERROR: All patch strategies failed for test patch"
    exit 1
fi

# Apply fix patch with multiple strategies
echo "=== Applying fix patch ==="
if git apply --verbose /home/fix.patch 2>&1; then
    echo "SUCCESS: git apply worked for fix patch"
elif git apply --verbose --ignore-space-change --ignore-whitespace /home/fix.patch 2>&1; then
    echo "SUCCESS: git apply with whitespace options worked for fix patch"
elif patch --batch --fuzz=3 -p1 < /home/fix.patch 2>&1; then
    echo "SUCCESS: patch with fuzz worked for fix patch"
else
    echo "ERROR: All patch strategies failed for fix patch"
    exit 1
fi

chmod +x gradlew

# Set up Gradle user home
export GRADLE_USER_HOME=/tmp/.gradle
mkdir -p $GRADLE_USER_HOME

# Configure Gradle for Thunderbird
cat > $GRADLE_USER_HOME/gradle.properties << 'EOF'
org.gradle.daemon=false
org.gradle.parallel=true
org.gradle.workers.max=4
org.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -XX:+UseG1GC
android.enableJetifier=true
android.useAndroidX=true
EOF

echo "=== Cleaning build artifacts ==="
./gradlew clean --no-daemon || true

echo "=== Running fix patch tests ==="
{test_cmd} --no-daemon --stacktrace --continue --parallel || true

echo "=== Collecting test results ==="
find . -name "TEST-*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== XML FILE: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END XML FILE ==="
done

find . -path "*/test-results/*" -name "*.xml" -type f 2>/dev/null | head -30 | while read file; do
    echo "=== TEST RESULT: $file ==="
    cat "$file" 2>/dev/null || echo "Could not read $file"
    echo "=== END TEST RESULT ==="
done
""".format(pr=self.pr, test_cmd=self.pr.test_command or "./gradlew clean test --max-workers 8"),
            ),
        ]

    def dockerfile(self) -> str:
        image = self.dependency()
        name = image.image_name()
        tag = image.image_tag()

        copy_commands = ""
        for file in self.files():
            copy_commands += f"COPY {file.name} /home/\n"

        prepare_commands = "RUN bash /home/prepare.sh"
        proxy_setup = ""
        proxy_cleanup = ""

        if self.global_env:
            proxy_host = None
            proxy_port = None

            for line in self.global_env.splitlines():
                match = re.match(
                    r"^ENV\s*(http[s]?_proxy)=http[s]?://([^:]+):(\d+)", line
                )
                if match:
                    proxy_host = match.group(2)
                    proxy_port = match.group(3)
                    break
            if proxy_host and proxy_port:
                proxy_setup = textwrap.dedent(
                    f"""
                    RUN mkdir -p ~/.gradle && \\
                        if [ ! -f "$HOME/.gradle/gradle.properties" ]; then \\
                            touch "$HOME/.gradle/gradle.properties"; \\
                        fi && \\
                        if ! grep -q "systemProp.http.proxyHost" "$HOME/.gradle/gradle.properties"; then \\
                            echo 'systemProp.http.proxyHost={proxy_host}' >> "$HOME/.gradle/gradle.properties" && \\
                            echo 'systemProp.http.proxyPort={proxy_port}' >> "$HOME/.gradle/gradle.properties" && \\
                            echo 'systemProp.https.proxyHost={proxy_host}' >> "$HOME/.gradle/gradle.properties" && \\
                            echo 'systemProp.https.proxyPort={proxy_port}' >> "$HOME/.gradle/gradle.properties"; \\
                        fi && \\
                        echo 'export GRADLE_USER_HOME=/root/.gradle' >> ~/.bashrc && \\
                        /bin/bash -c "source ~/.bashrc"
                """
                )

                proxy_cleanup = textwrap.dedent(
                    """
                    RUN rm -f ~/.gradle/gradle.properties
                """
                )
        return f"""FROM {name}:{tag}

{self.global_env}

{proxy_setup}

{copy_commands}

{prepare_commands}

{proxy_cleanup}

{self.clear_env}

"""


@Instance.register("thunderbird", "thunderbird-android")
class ThunderbirdAndroid(Instance):
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return ThunderbirdAndroidImageDefault(self.pr, self._config)

    def run(self, run_cmd: str = "") -> str:
        if run_cmd:
            return run_cmd

        return "bash /home/run.sh"

    def test_patch_run(self, test_patch_run_cmd: str = "") -> str:
        if test_patch_run_cmd:
            return test_patch_run_cmd

        return "bash /home/test-run.sh"

    def fix_patch_run(self, fix_patch_run_cmd: str = "") -> str:
        if fix_patch_run_cmd:
            return fix_patch_run_cmd

        return "bash /home/fix-run.sh"

    def parse_log(self, test_log: str) -> TestResult:
        """Parse test results from Gradle output including XML test reports."""
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()

        # Parse XML test result sections from Gradle output
        xml_sections = re.findall(r'=== XML(?:\s+FILE)?:\s*(.+?)\s*===\s*\n(.*?)\n=== END', test_log, re.DOTALL)
        xml_sections.extend(re.findall(r'=== TEST RESULT:\s*(.+?)\s*===\s*\n(.*?)\n=== END', test_log, re.DOTALL))

        for _, xml_content in xml_sections:
            # Parse <testcase> elements from XML
            testcase_pattern = r'<testcase[^>]*name="([^"]+)"[^>]*classname="([^"]+)"[^>]*(?:/>|>(.*?)</testcase>)'
            testcases = re.findall(testcase_pattern, xml_content, re.DOTALL)

            for match in testcases:
                test_name = match[0].strip()
                class_name = match[1].strip()
                test_content = match[2] if len(match) > 2 else ""

                # Format as ClassName.testMethodName
                full_test_name = f"{class_name}.{test_name}"

                # Determine test status
                if test_content:
                    if '<failure' in test_content or '<error' in test_content:
                        failed_tests.add(full_test_name)
                    elif '<skipped' in test_content:
                        skipped_tests.add(full_test_name)
                    else:
                        passed_tests.add(full_test_name)
                else:
                    # Self-closing testcase tag means passed
                    passed_tests.add(full_test_name)

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )
