# Copyright (c) 2024 Bytedance Ltd. and/or its affiliates

#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at

#      http://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""
Adapters for converting between different data formats.

This module provides conversion functions between TaskInstance (inference format)
and PullRequest/Dataset (harness format) to enable integration between the
inference and evaluation pipelines.
"""

from typing import Optional

from mobiledev_bench.inference.task_instance import TaskInstance
from mobiledev_bench.harness.pull_request import PullRequest, Base, ResolvedIssue


def detect_language(task: TaskInstance) -> str:
    """
    Detect the primary language/platform from the repository.

    This is a simple heuristic based on common mobile frameworks.
    For more accurate detection, consider analyzing the repository structure.
    """
    repo_lower = task.repo.lower()

    # Android (Kotlin/Java)
    if any(keyword in repo_lower for keyword in ['android', 'kotlin', 'droid']):
        return 'kotlin'

    # Flutter (Dart)
    if 'flutter' in repo_lower or 'dart' in repo_lower:
        return 'dart'

    # React Native (TypeScript/JavaScript)
    if any(keyword in repo_lower for keyword in ['react', 'native', 'rn']):
        return 'typescript'

    # iOS (Swift/Objective-C)
    if any(keyword in repo_lower for keyword in ['ios', 'swift', 'objective']):
        return 'swift'

    # Default to unknown
    return 'unknown'


def task_instance_to_pull_request(
    task: TaskInstance,
    tag: str = "",
    number_interval: str = "",
    lang: Optional[str] = None,
) -> PullRequest:
    """
    Convert TaskInstance format to PullRequest format.

    Args:
        task: TaskInstance object from inference module
        tag: Optional tag for categorization
        number_interval: Optional number interval for grouping
        lang: Optional language override (auto-detected if not provided)

    Returns:
        PullRequest object compatible with harness module
    """
    # Convert base dictionary to Base object
    base = Base(
        label=task.base.get("label", f"{task.org}:{task.base_ref}"),
        ref=task.base_ref,
        sha=task.base_commit
    )

    # Convert resolved_issues list to ResolvedIssue objects
    resolved_issues = []
    for issue in task.resolved_issues:
        if isinstance(issue, dict):
            resolved_issues.append(
                ResolvedIssue(
                    number=issue.get("number", 0),
                    title=issue.get("title", ""),
                    body=issue.get("body", "")
                )
            )
        elif isinstance(issue, (int, str)):
            # Handle simple issue numbers
            resolved_issues.append(
                ResolvedIssue(
                    number=int(issue),
                    title=f"Issue #{issue}",
                    body=""
                )
            )

    # Auto-detect language if not provided
    if lang is None:
        lang = detect_language(task)

    return PullRequest(
        org=task.org,
        repo=task.repo,
        number=task.number,
        state=task.state,
        title=task.title,
        body=task.body,
        base=base,
        resolved_issues=resolved_issues,
        fix_patch=task.fix_patch,
        test_patch=task.test_patch,
        tag=tag,
        number_interval=number_interval,
        lang=lang,
    )


def pull_request_to_task_instance(pr: PullRequest) -> TaskInstance:
    """
    Convert PullRequest format back to TaskInstance format.

    This is useful for round-trip conversion or for passing harness results
    back to inference pipeline.

    Args:
        pr: PullRequest object from harness module

    Returns:
        TaskInstance object compatible with inference module
    """
    # Convert Base object to dictionary
    base_dict = {
        "label": pr.base.label,
        "ref": pr.base.ref,
        "sha": pr.base.sha
    }

    # Convert ResolvedIssue objects to dictionaries
    resolved_issues_list = [
        {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body or ""
        }
        for issue in pr.resolved_issues
    ]

    # Construct instance_id
    instance_id = f"{pr.org}__{pr.repo}-{pr.number}"

    return TaskInstance(
        org=pr.org,
        repo=pr.repo,
        number=pr.number,
        instance_id=instance_id,
        state=pr.state,
        title=pr.title,
        body=pr.body or "",
        base=base_dict,
        resolved_issues=resolved_issues_list,
        fix_patch=pr.fix_patch,
        test_patch=pr.test_patch,
        problem_statement="",  # Not available in PullRequest
        hints=None,
    )
