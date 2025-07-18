from __future__ import annotations


import re
import time
import logging
import requests

from ghapi.core import GhApi
from unidiff import PatchSet
from typing import Callable, Iterator, Optional
from fastcore.net import HTTP404NotFoundError, HTTP403ForbiddenError
from requests.exceptions import SSLError, ConnectionError, Timeout, RequestException
from urllib3.exceptions import MaxRetryError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/using-keywords-in-issues-and-pull-requests
PR_KEYWORDS = {
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
}


class Repo:
    def __init__(self, owner: str, name: str, token: Optional[str] = None):
        """
        Init to retrieve target repository and create ghapi tool

        Args:
            owner (str): owner of target repository
            name (str): name of target repository
            token (str): github token
        """
        self.owner = owner
        self.name = name
        self.token = token
        self.api = GhApi(token=token)
        self.repo = self.call_api(self.api.repos.get, owner=owner, repo=name)

    def call_api(self, func: Callable, **kwargs) -> dict | None:
        """
        API call wrapper with rate limit handling (checks every 5 minutes if rate limit is reset)

        Args:
            func (callable): API function to call
            **kwargs: keyword arguments to pass to API function
        Return:
            values (dict): response object of `func`
        """
        while True:
            try:
                values = func(**kwargs)
                return values
            except HTTP403ForbiddenError:
                while True:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Rate limit exceeded for token {self.token[:10]}, "
                        f"waiting for 5 minutes, remaining calls: {rl.resources.core.remaining}"
                    )
                    if rl.resources.core.remaining > 0:
                        break
                    time.sleep(60 * 5)
            except HTTP404NotFoundError:
                logger.info(f"[{self.owner}/{self.name}] Resource not found {kwargs}")
                return None

    def extract_resolved_issues(self, pull: dict) -> list[str]:
        """
        Extract list of issues referenced by a PR

        Args:
            pull (dict): PR dictionary object from GitHub
        Return:
            resolved_issues (list): list of issue numbers referenced by PR
        """
        # Define 1. issue number regex pattern 2. comment regex pattern 3. keywords
        issues_pat = re.compile(r"(\w+)\s+\#(\d+)")
        comments_pat = re.compile(r"(?s)<!--.*?-->")

        # Construct text to search over for issue numbers from PR body and commit messages
        text = pull.title if pull.title else ""
        text += "\n" + (pull.body if pull.body else "")
        commits = self.get_all_loop(
            self.api.pulls.list_commits, pull_number=pull.number, quiet=True
        )
        commit_messages = [commit.commit.message for commit in commits]
        commit_text = "\n".join(commit_messages) if commit_messages else ""
        text += "\n" + commit_text
        # Remove comments from text
        text = comments_pat.sub("", text)
        # Look for issue numbers in text via scraping <keyword, number> patterns
        references = issues_pat.findall(text)
        resolved_issues_set = set()
        if references:
            for word, issue_num in references:
                if word.lower() in PR_KEYWORDS:
                    resolved_issues_set.add(issue_num)
        return list(resolved_issues_set)

    def get_all_loop(
        self,
        func: Callable,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        quiet: bool = False,
        **kwargs,
    ) -> Iterator:
        """
        Return all values from a paginated API endpoint.

        Args:
            func (callable): API function to call
            per_page (int): number of values to return per page
            num_pages (int): number of pages to return
            quiet (bool): whether to print progress
            **kwargs: keyword arguments to pass to API function
        """
        page = 1
        args = {
            "owner": self.owner,
            "repo": self.name,
            "per_page": per_page,
            **kwargs,
        }
        while True:
            try:
                # Get values from API call
                values = func(**args, page=page)
                yield from values
                if len(values) == 0:
                    break
                if not quiet:
                    rl = self.api.rate_limit.get()
                    logger.info(
                        f"[{self.owner}/{self.name}] Processed page {page} ({per_page} values per page). "
                        f"Remaining calls: {rl.resources.core.remaining}"
                    )
                if num_pages is not None and page >= num_pages:
                    break
                page += 1
            except Exception as e:
                # Rate limit handling
                logger.error(
                    f"[{self.owner}/{self.name}] Error processing page {page} "
                    f"w/ token {self.token[:10]} - {e}"
                )
                while True:
                    rl = self.api.rate_limit.get()
                    if rl.resources.core.remaining > 0:
                        break
                    logger.info(
                        f"[{self.owner}/{self.name}] Waiting for rate limit reset "
                        f"for token {self.token[:10]}, checking again in 5 minutes"
                    )
                    time.sleep(60 * 5)
        if not quiet:
            logger.info(
                f"[{self.owner}/{self.name}] Processed {(page - 1) * per_page + len(values)} values"
            )

    def get_all_issues(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all issues from repo

        Args:
            per_page (int): number of issues to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort issues
            sort (str): field to sort issues by
            state (str): state of issues to look for
            quiet (bool): whether to print progress
        """
        issues = self.get_all_loop(
            self.api.issues.list_for_repo,
            num_pages=num_pages,
            per_page=per_page,
            direction=direction,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return issues

    def get_all_pulls(
        self,
        per_page: int = 100,
        num_pages: Optional[int] = None,
        direction: str = "desc",
        sort: str = "created",
        state: str = "closed",
        quiet: bool = False,
    ) -> Iterator:
        """
        Wrapper for API call to get all PRs from repo

        Args:
            per_page (int): number of PRs to return per page
            num_pages (int): number of pages to return
            direction (str): direction to sort PRs
            sort (str): field to sort PRs by
            state (str): state of PRs to look for
            quiet (bool): whether to print progress
        """
        pulls = self.get_all_loop(
            self.api.pulls.list,
            num_pages=num_pages,
            direction=direction,
            per_page=per_page,
            sort=sort,
            state=state,
            quiet=quiet,
        )
        return pulls


def extract_problem_statement_and_hints(pull: dict, repo: Repo) -> tuple[str, str]:
    """
    Extract problem statement from issues associated with a pull request

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
    Return:
        text (str): problem statement
        hints (str): hints
    """
    text = ""
    all_hint_texts = list()
    for issue_number in pull["resolved_issues"]:
        issue = repo.call_api(
            repo.api.issues.get,
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
        )
        if issue is None:
            continue
        title = issue.title if issue.title else ""
        body = issue.body if issue.body else ""
        text += f"{title}\n{body}\n"
        issue_number = issue.number
        hint_texts = _extract_hints(pull, repo, issue_number)
        hint_text = "\n".join(hint_texts)
        all_hint_texts.append(hint_text)
    return text, "\n".join(all_hint_texts) if all_hint_texts else ""


def _extract_hints(pull: dict, repo: Repo, issue_number: int) -> list[str]:
    """
    Extract hints from comments associated with a pull request (before first commit)

    Args:
        pull (dict): PR dictionary object from GitHub
        repo (Repo): Repo object
        issue_number (int): issue number
    Return:
        hints (list): list of hints
    """
    # Get all commits in PR
    commits = repo.get_all_loop(
        repo.api.pulls.list_commits, pull_number=pull["number"], quiet=True
    )
    commits = list(commits)
    if len(commits) == 0:
        # If there are no comments, return no hints
        return []
    # Get time of first commit in PR
    commit_time = commits[0].commit.author.date  # str
    commit_time = time.mktime(time.strptime(commit_time, "%Y-%m-%dT%H:%M:%SZ"))
    # Get all comments in PR
    all_comments = repo.get_all_loop(
        repo.api.issues.list_comments, issue_number=issue_number, quiet=True
    )
    all_comments = list(all_comments)
    # Iterate through all comments, only keep comments created before first commit
    comments = list()
    for comment in all_comments:
        comment_time = time.mktime(
            time.strptime(comment.updated_at, "%Y-%m-%dT%H:%M:%SZ")
        )  # use updated_at instead of created_at
        if comment_time < commit_time:
            comments.append(comment)
        else:
            break
        # only include information available before the first commit was created
    # Keep text from comments
    comments = [comment.body for comment in comments]
    return comments


def fetch_diff_with_retry(diff_url: str, max_retries: int = 5, initial_delay: float = 1.0) -> str:
    """
    Fetch diff URL with retry logic and exponential backoff.
    
    Args:
        diff_url (str): The GitHub diff URL to fetch
        max_retries (int): Maximum number of retry attempts
        initial_delay (float): Initial delay in seconds before first retry
    
    Returns:
        str: The diff content as text
    
    Raises:
        RequestException: If all retry attempts fail
    """
    headers = {
        'User-Agent': 'mobilebench-crawler/1.0 (compatible; Python/requests)',
        'Accept': 'text/plain, application/x-patch, */*',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Fetching diff (attempt {attempt + 1}/{max_retries}): {diff_url}")
            
            response = requests.get(
                diff_url, 
                timeout=(10, 30),  # (connection timeout, read timeout)
                headers=headers,
                verify=True  # Keep SSL verification enabled
            )
            response.raise_for_status()
            
            logger.info(f"Successfully fetched diff on attempt {attempt + 1}")
            return response.text
            
        except (SSLError, ConnectionError, Timeout, MaxRetryError) as e:
            last_exception = e
            logger.warning(f"Network error on attempt {attempt + 1}: {type(e).__name__}: {e}")
            
            if attempt == max_retries - 1:
                logger.error(f"All {max_retries} attempts failed for {diff_url}")
                break
                
            # Exponential backoff with jitter
            delay = initial_delay * (2 ** attempt) + (0.1 * attempt)  # Add small jitter
            logger.info(f"Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            
        except RequestException as e:
            # For other HTTP errors (404, 403, etc.), don't retry
            logger.error(f"HTTP error (not retrying): {type(e).__name__}: {e}")
            raise e
        except Exception as e:
            # For unexpected errors, log and raise
            logger.error(f"Unexpected error: {type(e).__name__}: {e}")
            raise e
    
    # If we get here, all retries failed
    raise last_exception

def extract_patches(pull: dict, repo, max_retries: int = 5) -> tuple[str, str]:
    """
    Get patch and test patch from PR with robust error handling.

    Args:
        pull (dict): PR dictionary object from GitHub
        repo: Repo object
        max_retries (int): Maximum number of retry attempts for network requests
        
    Return:
        patch_change_str (str): gold patch (non-test changes)
        patch_test_str (str): test patch (test-related changes)
        
    Raises:
        RequestException: If unable to fetch the diff after all retries
        ValueError: If the diff URL is invalid or patch parsing fails
    """
    
    # Validate input
    if not pull.get("diff_url"):
        raise ValueError(f"No diff_url found in pull request data")
    
    try:
        # Fetch the patch with retry logic
        patch = fetch_diff_with_retry(pull["diff_url"], max_retries=max_retries)
        
        if not patch.strip():
            logger.warning(f"Empty patch received for {pull['diff_url']}")
            return "", ""
            
    except Exception as e:
        logger.error(f"Failed to fetch patch for {repo}: {e}")
        # You can choose to re-raise or return empty strings to skip this PR
        raise e  # Re-raise to halt processing
        # Or alternatively, to skip this PR and continue:
        # return "", ""
    
    # Initialize patch strings
    patch_test = ""
    patch_fix = ""

    android_test_words = [
        # Standard Android test directories
        "test",
        "tests", 
        "androidTest",        # Android instrumented tests
        "androidtest",
        "unitTest",
        "unittest",
        "integrationTest",
        "integrationtest",
        
        # Test source sets
        "src/test",
        "src/androidTest",
        "src/testDebug",
        "src/testRelease",
        
        # Common test folders
        "testing",
        "testutils",
        "testUtil",
        "test-utils",
        "testdata",
        "test-data",
        "testassets",
        "test-assets",
        
        # Specific test types
        "espresso",           # UI testing framework
        "robolectric",        # Unit testing framework
        "mockito",            # Mocking framework
        "junit",              # Testing framework
        
        # Test categories
        "uitest",
        "ui-test",
        "e2e",
        "e2etest",
        "functional",
        "functionaltest",
        "smoke",
        "smoketest",
        "regression",
        "regressiontest",
        
        # Common test file patterns
        "mock",
        "stub",
        "fake",
        "testdouble",
        "fixture",
        "testfixture"
    ]

    try:
        # Parse the patch and separate test vs non-test changes
        patch_set = PatchSet(patch)
        
        for hunk in patch_set:
            if hunk.path and any(test_word in hunk.path.lower() for test_word in android_test_words):
                patch_test += str(hunk)
            else:
                patch_fix += str(hunk)
                
        logger.info(f"Successfully parsed patch: {len(patch_set)} files, "
                   f"test changes: {len(patch_test)} chars, "
                   f"fix changes: {len(patch_fix)} chars")
                   
    except Exception as e:
        logger.error(f"Failed to parse patch for {repo}: {e}")
        # You might want to log the patch content for debugging
        logger.debug(f"Problematic patch content (first 500 chars): {patch[:500]}")
        raise e
    
    return patch_fix, patch_test

# Alternative version that skips problematic PRs instead of failing
def extract_patches_safe(pull: dict, repo, max_retries: int = 5) -> tuple[str, str] | None:
    """
    Safe version that returns None if extraction fails, allowing processing to continue.
    
    Returns:
        tuple[str, str] | None: (patch_fix, patch_test) or None if extraction failed
    """
    try:
        return extract_patches(pull, repo, max_retries)
    except Exception as e:
        logger.warning(f"Skipping PR {pull.get('number', 'unknown')} for {repo} due to error: {e}")
        return None