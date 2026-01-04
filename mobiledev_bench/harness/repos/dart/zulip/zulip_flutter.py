import re
from typing import Optional, Union
from mobiledev_bench.harness.image import Config, File, Image
from mobiledev_bench.harness.instance import Instance
from mobiledev_bench.harness.pull_request import PullRequest
from mobiledev_bench.harness.test_result import TestResult


class ZulipFlutterImageBase(Image):
    """Base image with Flutter latest (3.38.5) for newer PRs"""
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
        return "ghcr.io/cirruslabs/flutter:latest"

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

# Install SQLite (required by zulip-flutter test suite)
RUN apt-get update && apt-get install -y libsqlite3-dev && rm -rf /var/lib/apt/lists/*

{code}

{self.clear_env}

"""


class ZulipFlutterImageBaseFlutter322(Image):
    """Base image with Flutter 3.22.3 for PRs requiring Flutter 3.21+ pre-releases"""
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
        return "ghcr.io/cirruslabs/flutter:3.22.3"

    def image_tag(self) -> str:
        return "base-flutter-3.22"

    def workdir(self) -> str:
        return "base-flutter-3.22"

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

# Install SQLite (required by zulip-flutter test suite)
RUN apt-get update && apt-get install -y libsqlite3-dev && rm -rf /var/lib/apt/lists/*

{code}

{self.clear_env}

"""


class ZulipFlutterImageBaseFlutter319(Image):
    """Base image with Flutter 3.19.6 for PRs requiring Flutter 3.16+ pre-releases with Dart 3.3+"""
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
        return "ghcr.io/cirruslabs/flutter:3.19.6"

    def image_tag(self) -> str:
        return "base-flutter-3.19"

    def workdir(self) -> str:
        return "base-flutter-3.19"

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

# Install SQLite (required by zulip-flutter test suite)
RUN apt-get update && apt-get install -y libsqlite3-dev && rm -rf /var/lib/apt/lists/*

{code}

{self.clear_env}

"""


class ZulipFlutterImageBaseFlutter340Pre(Image):
    """Base image with Flutter 3.40.0-0.2.pre for PRs requiring Flutter 3.38+ pre-releases with Dart 3.11+"""
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
        return "ghcr.io/cirruslabs/flutter:3.40.0-0.2.pre"

    def image_tag(self) -> str:
        return "base-flutter-3.40-pre"

    def workdir(self) -> str:
        return "base-flutter-3.40-pre"

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

# Install SQLite (required by zulip-flutter test suite)
RUN apt-get update && apt-get install -y libsqlite3-dev && rm -rf /var/lib/apt/lists/*

{code}

{self.clear_env}

"""


class ZulipFlutterImageDefault(Image):
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
        # Map PRs to Flutter versions based on pubspec.yaml constraints
        if self.pr.number == 304:
            # PR requiring Flutter 3.16+ pre-releases that need Dart 3.3+
            return ZulipFlutterImageBaseFlutter319(self.pr, self._config)
        elif self.pr.number == 589:
            # PRs requiring Flutter 3.21+ pre-releases
            return ZulipFlutterImageBaseFlutter322(self.pr, self._config)
        elif self.pr.number in [1879, 1911, 1915, 1952]:
            # PRs requiring Flutter 3.40.0-0.2.pre with Dart 3.11+
            return ZulipFlutterImageBaseFlutter340Pre(self.pr, self._config)
        else:
            return ZulipFlutterImageBase(self.pr, self._config)

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

# Try to get dependencies, if it fails due to version conflicts, try upgrading
if ! flutter pub get; then
    echo "flutter pub get failed, attempting flutter pub upgrade --major-versions"
    flutter pub upgrade --major-versions
fi

flutter test || true
""".format(pr=self.pr),
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
{test_cmd}

""".format(pr=self.pr, test_cmd=self.pr.test_command or "flutter test"),
            ),
            File(
                ".",
                "test-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
git apply --whitespace=nowarn /home/test.patch
{test_cmd}

""".format(pr=self.pr, test_cmd=self.pr.test_command or "flutter test"),
            ),
            File(
                ".",
                "fix-run.sh",
                """#!/bin/bash
set -e

cd /home/{pr.repo}
git apply --whitespace=nowarn /home/test.patch /home/fix.patch
{test_cmd}

""".format(pr=self.pr, test_cmd=self.pr.test_command or "flutter test"),
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


@Instance.register("zulip", "zulip-flutter")
class ZulipFlutter(Instance):
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return ZulipFlutterImageDefault(self.pr, self._config)

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
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()

        # Flutter test output format explanation:
        # Lines show cumulative counters: "00:02 +13 -1: test name"
        # +13 = total passed so far, -1 = total failed so far
        # A test with [E] suffix indicates a failure
        # A test without [E] that appears in the log indicates a pass

        # Pattern for test lines (passed or failed)
        test_line_pattern = re.compile(r"^\d+:\d+ \+\d+( -\d+)?: (.+)$")

        # Additional patterns for alternative output formats
        passed_alt_res = [
            re.compile(r"^✓ (.+)$"),  # ✓ test name (verbose mode)
        ]

        failed_alt_res = [
            re.compile(r"^✗ (.+)$"),  # ✗ test name (verbose mode)
        ]

        skipped_res = [
            re.compile(r"^⊘ (.+)$"),  # ⊘ test name
            re.compile(r"^\s*SKIP: (.+)$"),  # SKIP: test name
        ]

        for line in test_log.splitlines():
            # Check for test line with standard format
            m = test_line_pattern.match(line)
            if m:
                test_name = m.group(2)
                # Skip summary lines
                if test_name in ["Some tests failed.", "All tests passed!"]:
                    continue

                # Check if this is a failure (marked with [E])
                if test_name.endswith(" [E]"):
                    test_name = test_name[:-4]  # Remove [E] suffix
                    # Count failed loading lines (compilation errors, missing files)
                    if test_name.startswith("loading "):
                        failed_tests.add(test_name)
                        if test_name in passed_tests:
                            passed_tests.remove(test_name)
                    else:
                        failed_tests.add(test_name)
                        if test_name in passed_tests:
                            passed_tests.remove(test_name)
                else:
                    # Skip successful loading lines (not actual test executions)
                    if test_name.startswith("loading "):
                        continue
                    # It's a pass (appears in log without [E])
                    if test_name not in failed_tests:
                        passed_tests.add(test_name)
                continue

            # Check alternative pass formats
            for passed_re in passed_alt_res:
                m = passed_re.match(line)
                if m and m.group(1) not in failed_tests:
                    passed_tests.add(m.group(1))
                    break

            # Check alternative fail formats
            for failed_re in failed_alt_res:
                m = failed_re.match(line)
                if m:
                    failed_tests.add(m.group(1))
                    if m.group(1) in passed_tests:
                        passed_tests.remove(m.group(1))
                    break

            # Check skip formats
            for skipped_re in skipped_res:
                m = skipped_re.match(line)
                if m:
                    skipped_tests.add(m.group(1))
                    break

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )
