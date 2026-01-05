import re
import json
from typing import Optional, Union

from mobiledev_bench.harness.image import Config, File, Image
from mobiledev_bench.harness.instance import Instance
from mobiledev_bench.harness.pull_request import PullRequest
from mobiledev_bench.harness.test_result import TestResult


class MetamaskMobileImageBase(Image):
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

    def image_tag(self) -> str:
        return "base"

    def workdir(self) -> str:
        return "base"

    def files(self) -> list[File]:
        return []

    def dockerfile(self) -> str:
        image_name = self.dependency()
        if isinstance(image_name, Image):
            image_name = image_name.image_full_name()

        if self.config.need_clone:
            code = f"RUN git clone https://github.com/{self.pr.org}/{self.pr.repo}.git /home/{self.pr.repo}"
        else:
            code = f"COPY {self.pr.repo} /home/{self.pr.repo}"

        return f"""FROM {image_name}
USER root
{self.global_env}

WORKDIR /home/
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && apt-get install -y git

{code}

{self.clear_env}

"""


class MetamaskMobileImageDefault(Image):
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
        return MetamaskMobileImageBase(self.pr, self._config)

    def image_tag(self) -> str:
        return f"pr-{self.pr.number}"

    def workdir(self) -> str:
        return f"pr-{self.pr.number}"

    def files(self) -> list[File]:
        repo_name = self.pr.repo
        test_cmd = self.pr.test_command if self.pr.test_command else "yarn test --verbose"
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
                """#!/bin/bash
set -e

cd /home/{pr.repo}
git reset --hard
git checkout {pr.base.sha}
yarn install
{test_cmd} || true
""".format(pr=self.pr, test_cmd=test_cmd),
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
{test_cmd}

""".format(pr=self.pr, test_cmd=test_cmd),
            ),
            File(
                ".",
                "test-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
if ! git apply --reject --whitespace=fix --exclude='*.lock' --exclude='*.lockb' --exclude='yarn.lock' --exclude='package-lock.json' /home/test.patch; then
    echo "Error: git apply failed" >&2
    exit 1
fi
{test_cmd}

""".format(pr=self.pr, test_cmd=test_cmd),
            ),
            File(
                ".",
                "fix-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
if ! git apply --reject --whitespace=fix --exclude='*.lock' --exclude='*.lockb' --exclude='yarn.lock' --exclude='package-lock.json' /home/test.patch /home/fix.patch; then
    echo "Error: git apply failed" >&2
    exit 1
fi
{test_cmd}

""".format(pr=self.pr, test_cmd=test_cmd),
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

        return f"""FROM {name}:{tag}

{self.global_env}

{copy_commands}

{prepare_commands}

{self.clear_env}

"""


@Instance.register("MetaMask", "metamask-mobile")
class MetamaskMobile(Instance):
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return MetamaskMobileImageDefault(self.pr, self._config)

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
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()

        # Jest/Yarn test output patterns
        passed_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:[✓√]|PASS|PASSED)\s+(.+?)(?:\s*\(\d+\.?\d* (?:ms|s)\))?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in passed_pattern.finditer(log):
            test_name = match.group(1).strip()
            passed_tests.add(test_name)

        # Extract failed tests
        failed_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:[✕x]|FAIL|FAILED)\s+(.+?)(?:\s*\(\d+\.?\d* (?:ms|s)\))?\s*$|^\s*at Object\.<anonymous>\s*\((.+?):\d+:\d+\)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in failed_pattern.finditer(log):
            test_name = match.group(1) or match.group(2)
            if test_name:
                failed_tests.add(test_name.strip())

        # Extract skipped tests
        skipped_pattern = re.compile(
            r"^\s*(?:\[\s*\d+\s*\]\s*)?(?:SKIP|SKIPPED|○)\s+(.+?)(?:\s*\(\d+\.?\d* (?:ms|s)\))?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in skipped_pattern.finditer(log):
            test_name = match.group(1).strip()
            skipped_tests.add(test_name)

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )
