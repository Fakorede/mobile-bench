import re
import json
from typing import Optional, Union

from mobiledev_bench.harness.image import Config, File, Image
from mobiledev_bench.harness.instance import Instance
from mobiledev_bench.harness.pull_request import PullRequest
from mobiledev_bench.harness.test_result import TestResult


class ImageDefault(Image):
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> str:
        return "node:20"

    def image_prefix(self) -> str:
        return "mobiledevbench"

    def image_tag(self) -> str:
        return f"pr-{self.pr.number}"

    def workdir(self) -> str:
        return f"pr-{self.pr.number}"

    def files(self) -> list[File]:
        repo_name = self.pr.repo
        test_cmd = self.pr.test_command if self.pr.test_command else "NODE_OPTIONS='--experimental-vm-modules --max-old-space-size=4096' npx --no-install jest --verbose"

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
                "prepare.sh",
                f"""ls -la
###ACTION_DELIMITER###
npm install -g yarn
###ACTION_DELIMITER###
yarn install
###ACTION_DELIMITER###
echo -e '#!/bin/bash\\n{test_cmd}' > test_commands.sh && chmod +x test_commands.sh
###ACTION_DELIMITER###
bash test_commands.sh""",
            ),
            File(
                ".",
                "run.sh",
                f"""#!/bin/bash
cd /home/{repo_name}
{test_cmd}

""",
            ),
            File(
                ".",
                "test-run.sh",
                f"""#!/bin/bash
cd /home/{repo_name}
git -C /home/{repo_name} apply --reject --whitespace=fix --exclude='*.lock' /home/test.patch || true
{test_cmd}

""",
            ),
            File(
                ".",
                "fix-run.sh",
                f"""#!/bin/bash
cd /home/{repo_name}
git -C /home/{repo_name} apply --reject --whitespace=fix --exclude='*.lock' /home/test.patch /home/fix.patch || true
{test_cmd}

""",
            ),
        ]

    def dockerfile(self) -> str:
        copy_commands = ""
        for file in self.files():
            copy_commands += f"COPY {file.name} /home/\n"

        dockerfile_content = """
FROM node:20

## Set noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# Install basic requirements
# For example: RUN apt-get update && apt-get install -y git
# For example: RUN yum install -y git
# For example: RUN apk add --no-cache git
RUN apt-get update && apt-get install -y git

# Ensure bash is available
RUN if [ ! -f /bin/bash ]; then         if command -v apk >/dev/null 2>&1; then             apk add --no-cache bash;         elif command -v apt-get >/dev/null 2>&1; then             apt-get update && apt-get install -y bash;         elif command -v yum >/dev/null 2>&1; then             yum install -y bash;         else             exit 1;         fi     fi

WORKDIR /home/
COPY fix.patch /home/
COPY test.patch /home/
RUN git clone https://github.com/{pr.org}/{pr.repo}.git /home/{pr.repo}

WORKDIR /home/{pr.repo}
RUN git reset --hard
RUN git checkout {pr.base.sha}

# Install dependencies
RUN yarn install
"""
        dockerfile_content += f"""
{copy_commands}
"""
        return dockerfile_content.format(pr=self.pr)


@Instance.register("RocketChat", "Rocket.Chat.ReactNative")
class ROCKET_CHAT_REACTNATIVE(Instance):
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return ImageDefault(self.pr, self._config)

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

    def parse_log(self, log: str) -> TestResult:
        # Parse the log content and extract test execution results.
        passed_tests = set()  # Tests that passed successfully
        failed_tests = set()  # Tests that failed
        skipped_tests = set()  # Tests that were skipped

        # Extract passed tests using regex
        passed_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:[✓√]|PASS|PASSED)\s+(.+?)(?:\s*\(\d+\.?\d*\s*(?:ms|s)\))?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in passed_pattern.finditer(log):
            test_name = match.group(1).strip()
            # Remove timing suffix if present
            test_name = re.sub(r'\s*\(\d+\.?\d*\s*(?:ms|s)\)\s*$', '', test_name).strip()
            passed_tests.add(test_name)

        # Extract failed tests using regex
        failed_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:[✕x]|FAIL|FAILED)\s+(.+?)(?:\s*\(\d+\.?\d*\s*(?:ms|s)\))?\s*$|^\s*at Object\.<anonymous>\s*\((.+?):\d+:\d+\)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in failed_pattern.finditer(log):
            test_name = match.group(1) or match.group(2)
            if test_name:
                test_name = test_name.strip()
                # Remove timing suffix if present
                test_name = re.sub(r'\s*\(\d+\.?\d*\s*(?:ms|s)\)\s*$', '', test_name).strip()
                failed_tests.add(test_name)

        # Extract skipped tests using regex
        skipped_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:SKIP|SKIPPED|○)\s+(.+?)(?:\s*\(\d+\.?\d*\s*(?:ms|s)\))?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in skipped_pattern.finditer(log):
            test_name = match.group(1).strip()
            # Remove timing suffix if present
            test_name = re.sub(r'\s*\(\d+\.?\d*\s*(?:ms|s)\)\s*$', '', test_name).strip()
            skipped_tests.add(test_name)

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )
