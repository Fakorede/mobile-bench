# utils.py 
import os
import re
import ast
import chardet
import subprocess
from argparse import ArgumentTypeError
from git import Repo
from pathlib import Path
from tempfile import TemporaryDirectory

import logging
import hashlib
import pickle
from typing import Dict, List, Set, Tuple, Optional
# from mobilebench.inference.android_config import AndroidProjectConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


DIFF_PATTERN = re.compile(r"^diff(?:.*)")
PATCH_PATTERN = re.compile(
    r"(?:diff[\w\_\.\ \/\-]+\n)?\-\-\-\s+a\/(?:.*?)\n\+\+\+\s+b\/(?:.*?)(?=diff\ |\-\-\-\ a\/|\Z)",
    re.DOTALL,
)
PATCH_FILE_PATTERN = re.compile(r"\-\-\-\s+a\/(?:.+)\n\+\+\+\s+b\/(?:.+)")
PATCH_HUNK_PATTERN = re.compile(
    r"\@\@\s+\-(\d+),(\d+)\s+\+(\d+),(\d+)\s+\@\@(.+?)(?=diff\ |\-\-\-\ a\/|\@\@\ \-|\Z)",
    re.DOTALL,
)


def get_first_idx(charlist):
    first_min = charlist.index("-") if "-" in charlist else len(charlist)
    first_plus = charlist.index("+") if "+" in charlist else len(charlist)
    return min(first_min, first_plus)


def get_last_idx(charlist):
    char_idx = get_first_idx(charlist[::-1])
    last_idx = len(charlist) - char_idx
    return last_idx + 1


def strip_content(hunk):
    first_chars = list(map(lambda x: None if not len(x) else x[0], hunk.split("\n")))
    first_idx = get_first_idx(first_chars)
    last_idx = get_last_idx(first_chars)
    new_lines = list(map(lambda x: x.rstrip(), hunk.split("\n")[first_idx:last_idx]))
    new_hunk = "\n" + "\n".join(new_lines) + "\n"
    return new_hunk, first_idx - 1


def get_hunk_stats(pre_start, pre_len, post_start, post_len, hunk, total_delta):
    stats = {"context": 0, "added": 0, "subtracted": 0}
    hunk = hunk.split("\n", 1)[-1].strip("\n")
    for line in hunk.split("\n"):
        if line.startswith("-"):
            stats["subtracted"] += 1
        elif line.startswith("+"):
            stats["added"] += 1
        else:
            stats["context"] += 1
    context = stats["context"]
    added = stats["added"]
    subtracted = stats["subtracted"]
    pre_len = context + subtracted
    post_start = pre_start + total_delta
    post_len = context + added
    total_delta = total_delta + (post_len - pre_len)
    return pre_start, pre_len, post_start, post_len, total_delta


def repair_patch(model_patch):
    if model_patch is None:
        return None
    model_patch = model_patch.lstrip("\n")
    new_patch = ""
    for patch in PATCH_PATTERN.findall(model_patch):
        total_delta = 0
        diff_header = DIFF_PATTERN.findall(patch)
        if diff_header:
            new_patch += diff_header[0] + "\n"
        patch_header = PATCH_FILE_PATTERN.findall(patch)[0]
        if patch_header:
            new_patch += patch_header + "\n"
        for hunk in PATCH_HUNK_PATTERN.findall(patch):
            pre_start, pre_len, post_start, post_len, content = hunk
            pre_start, pre_len, post_start, post_len, total_delta = get_hunk_stats(
                *list(map(lambda x: int(x) if x.isnumeric() else x, hunk)), total_delta
            )
            new_patch += (
                f"@@ -{pre_start},{pre_len} +{post_start},{post_len} @@{content}"
            )
    return new_patch


def extract_minimal_patch(model_patch):
    model_patch = model_patch.lstrip("\n")
    new_patch = ""
    for patch in PATCH_PATTERN.findall(model_patch):
        total_delta = 0
        diff_header = DIFF_PATTERN.findall(patch)
        patch_header = PATCH_FILE_PATTERN.findall(patch)[0]
        if patch_header:
            new_patch += patch_header + "\n"
        for hunk in PATCH_HUNK_PATTERN.findall(patch):
            pre_start, pre_len, post_start, post_len, content = hunk
            pre_start, pre_len, post_start, post_len, content = list(
                map(lambda x: int(x) if x.isnumeric() else x, hunk)
            )
            content, adjust_pre_start = strip_content(content)
            pre_start += adjust_pre_start
            pre_start, pre_len, post_start, post_len, total_delta = get_hunk_stats(
                pre_start, pre_len, post_start, post_len, content, total_delta
            )
            new_patch += (
                f"@@ -{pre_start},{pre_len} +{post_start},{post_len} @@{content}"
            )
    return new_patch


def extract_diff(response):
    """
    Extracts the diff from a response formatted in different ways
    """
    if response is None:
        return None
    diff_matches = []
    other_matches = []
    pattern = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    for code, match in pattern.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    if diff_matches:
        return diff_matches[0]
    if other_matches:
        return other_matches[0]
    return response.split("</s>")[0]


def is_test(name, test_phrases=None):
   """
   Detect test files for Android projects
   """
   if test_phrases is None:
       # Android-specific test patterns
       test_phrases = [
           "test", "tests", "testing", 
           "androidtest", "instrumentedtest", "espresso",
           "unittest", "integrationtest", "uitest"
       ]
   
   # Convert to lowercase for case-insensitive matching
   name_lower = name.lower()
   
   # Android test directory patterns
   android_test_dirs = [
       "/test/",           # Standard test directory
       "/androidtest/",    # Android instrumented tests
       "/instrumentedtest/", # Alternative instrumented test naming
       "/src/test/",       # Gradle test source set
       "/src/androidtest/", # Gradle Android test source set
       "/src/instrumentedtest/", # Alternative naming
   ]
   
   # Check if file is in a test directory
   for test_dir in android_test_dirs:
       if test_dir in name_lower:
           return True
   
   # Check for test file naming patterns
   words = set(re.split(r" |_|\/|\.", name_lower))
   if any(word in words for word in test_phrases):
       return True
   
   # Android-specific test file patterns
   android_test_patterns = [
       r".*test\.java$",           # SomethingTest.java
       r".*test\.kt$",             # SomethingTest.kt
       r".*tests\.java$",          # SomethingTests.java
       r".*tests\.kt$",            # SomethingTests.kt
       r"test.*\.java$",           # TestSomething.java
       r"test.*\.kt$",             # TestSomething.kt
       r".*spec\.java$",           # SomethingSpec.java
       r".*spec\.kt$",             # SomethingSpec.kt
       r".*testcase\.java$",       # SomethingTestCase.java
       r".*testcase\.kt$",         # SomethingTestCase.kt
   ]
   
   # Check file name patterns
   for pattern in android_test_patterns:
       if re.match(pattern, name_lower):
           return True
   
   # Check for common Android test class naming in file content detection
   # (This is a filename-based check, but catches common patterns)
   test_class_indicators = [
       "instrumentation", "espresso", "androidjunit", 
       "robolectric", "mockito", "junit"
   ]
   
   for indicator in test_class_indicators:
       if indicator in name_lower:
           return True
   
   return False


class ContextManager:
    def __init__(self, repo_path, base_commit, verbose=False):
        self.repo_path = Path(repo_path).resolve().as_posix()
        self.old_dir = os.getcwd()
        self.base_commit = base_commit
        self.verbose = verbose

    def __enter__(self):
        os.chdir(self.repo_path)
        cmd = f"git reset --hard {self.base_commit} && git clean -fdxq"
        if self.verbose:
            subprocess.run(cmd, shell=True, check=True)
        else:
            subprocess.run(
                cmd,
                shell=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return self

    def get_environment(self):
        raise NotImplementedError()  # TODO: activate conda environment and return the environment file

    def get_readme_files(self):
        files = os.listdir(self.repo_path)
        files = list(filter(lambda x: os.path.isfile(x), files))
        files = list(filter(lambda x: x.lower().startswith("readme"), files))
        return files

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.chdir(self.old_dir)


class AutoContextManager(ContextManager):
    """Automatically clones the repo if it doesn't exist"""

    def __init__(self, instance, root_dir=None, verbose=False, token=None):
        if token is None:
            token = os.environ.get("GITHUB_TOKENS", "git")
        self.tempdir = None
        if root_dir is None:
            self.tempdir = TemporaryDirectory()
            root_dir = self.tempdir.name
        self.root_dir = root_dir
        repo_dir = os.path.join(self.root_dir, instance["repo"].replace("/", "__"))

        if not os.path.exists(repo_dir):
            # repo_url = (
            #     f"https://{token}@github.com/swe-bench-repos/"
            #     + instance["repo"].replace("/", "__")
            #     + ".git"
            # )
            owner, repo = instance["repo"].split("/")
            repo_url = f"https://github.com/{owner}/{repo}.git"
            if verbose:
                print(f"Cloning {instance['repo']} to {root_dir}")
            # Clone with full history
            Repo.clone_from(repo_url, repo_dir, multi_options=['--no-single-branch'])

        super().__init__(repo_dir, instance["base_commit"], verbose=verbose)
        self.instance = instance

    def __enter__(self):
        os.chdir(self.repo_path)

        # DEBUG: Log repository state
        print(f"=== REPO DEBUG ===")
        print(f"Repository path: {self.repo_path}")
        print(f"Target commit: {self.base_commit}")
        
        # Check what's actually in the directory
        import subprocess
        result = subprocess.run("find . -name '*.java' | head -5", shell=True, capture_output=True, text=True, cwd=self.repo_path)
        print(f"Java files found: {result.stdout}")
        
        result = subprocess.run("git status --porcelain", shell=True, capture_output=True, text=True, cwd=self.repo_path)
        print(f"Git status: {result.stdout}")
        
        result = subprocess.run("git log --oneline -3", shell=True, capture_output=True, text=True, cwd=self.repo_path)
        print(f"Recent commits: {result.stdout}")
        
        # First, try to ensure we have the commit
        if not self._commit_exists(self.base_commit):
            print(f"Commit {self.base_commit} does not exist, trying to fetch...")
            if not self._fetch_commit(self.base_commit):
                raise ValueError(f"Commit {self.base_commit} not found and could not be fetched")
        
        # Now try the reset
        cmd = f"git reset --hard {self.base_commit} && git clean -fdxq"
        try:
            print(f"Executing: {cmd}")
            if self.verbose:
                subprocess.run(cmd, shell=True, check=True)
            else:
                # subprocess.run(
                #     cmd,
                #     shell=True,
                #     check=True,
                #     stdout=subprocess.DEVNULL,
                #     stderr=subprocess.DEVNULL,
                # )
                result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
                print(f"Reset result: stdout={result.stdout}, stderr={result.stderr}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to reset to commit {self.base_commit}: {e}")
        
        result = subprocess.run("find . -name '*.java' | head -5", shell=True, capture_output=True, text=True, cwd=self.repo_path)
        print(f"Java files after reset: {result.stdout}")
        print(f"=== END REPO DEBUG ===")
        
        return self
    
    def _commit_exists(self, commit_hash):
        """Check if a commit exists in the repository."""
        try:
            result = subprocess.run(
                f"git cat-file -e {commit_hash}",
                shell=True,
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except:
            return False
    
    def _fetch_commit(self, commit_hash):
        """Try to fetch a specific commit."""
        fetch_commands = [
            "git fetch --all --tags --prune",
            f"git fetch origin {commit_hash}",
            "git fetch --unshallow",
            "git fetch --depth=1000"
        ]
        
        for cmd in fetch_commands:
            try:
                subprocess.run(
                    cmd,
                    shell=True,
                    check=True,
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True
                )
                if self._commit_exists(commit_hash):
                    if self.verbose:
                        print(f"Successfully fetched commit {commit_hash}")
                    return True
            except subprocess.CalledProcessError:
                continue
        
        return False

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.tempdir is not None:
            self.tempdir.cleanup()
        return super().__exit__(exc_type, exc_val, exc_tb)


def get_imported_modules(filename):
    with open(filename) as file:
        tree = ast.parse(file.read(), filename)
    return [
        node
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def resolve_module_to_file(module, level, root_dir):
    components = module.split(".")
    if level > 0:
        components = components[:-level]
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if dirpath.endswith(os.sep.join(components)):
            return [
                os.path.join(dirpath, filename)
                for filename in filenames
                if filename.endswith(".py")
            ]
    return []


def ingest_file_directory_contents(target_file, root_dir):
    imported_files = []
    files_to_check = [target_file]
    while files_to_check:
        current_file = files_to_check.pop()
        imported_files.append(current_file)
        imports = get_imported_modules(current_file)
        for node in imports:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    files = resolve_module_to_file(alias.name, 0, root_dir)
                    for file in files:
                        if file not in imported_files and file not in files_to_check:
                            files_to_check.append(file)
            elif isinstance(node, ast.ImportFrom):
                files = resolve_module_to_file(node.module, node.level, root_dir)
                for file in files:
                    if file not in imported_files and file not in files_to_check:
                        files_to_check.append(file)
    return imported_files


def detect_encoding(filename):
    """
    Detect the encoding of a file
    """
    with open(filename, "rb") as file:
        rawdata = file.read()
    return chardet.detect(rawdata)["encoding"]


def list_files(root_dir, include_tests=False):
    files = []
    android_extensions = AndroidProjectConfig.INCLUDED_EXTENSIONS

    for pattern in android_extensions:
        for filename in Path(root_dir).rglob(pattern):
            if not include_tests and is_test(filename.as_posix()):
                continue
            files.append(filename.relative_to(root_dir).as_posix())
    return files


def ingest_directory_contents(root_dir, include_tests=False):
    files_content = {}
    for relative_path in list_files(root_dir, include_tests=include_tests):
        filename = os.path.join(root_dir, relative_path)
        encoding = detect_encoding(filename)
        if encoding is None:
            content = "[BINARY DATA FILE]"
        else:
            try:
                with open(filename, encoding=encoding) as file:
                    content = file.read()
            except (UnicodeDecodeError, LookupError):
                content = "[BINARY DATA FILE]"
        files_content[relative_path] = content
    return files_content


def string_to_bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise ArgumentTypeError(
            f"Truthy value expected: got {v} but expected one of yes/no, true/false, t/f, y/n, 1/0 (case insensitive)."
        )
    

class ContextCache:
    """Cache for processed contexts to avoid recomputation"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = Path(cache_dir or "cache/contexts")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_cache_key(self, instance_id: str, file_source: str, prompt_style: str, 
                      files_hash: str) -> str:
        """Generate cache key for instance"""
        key_data = f"{instance_id}_{file_source}_{prompt_style}_{files_hash}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _get_files_hash(self, files_dict: Dict[str, str]) -> str:
        """Generate hash of file contents"""
        content = "".join(f"{k}:{v}" for k, v in sorted(files_dict.items()))
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, instance_id: str, file_source: str, prompt_style: str, 
           files_dict: Dict[str, str]) -> Optional[str]:
        """Get cached prompt if available"""
        files_hash = self._get_files_hash(files_dict)
        cache_key = self._get_cache_key(instance_id, file_source, prompt_style, files_hash)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache for {instance_id}: {e}")
                
        return None
    
    def set(self, instance_id: str, file_source: str, prompt_style: str, 
           files_dict: Dict[str, str], prompt: str) -> None:
        """Cache processed prompt"""
        files_hash = self._get_files_hash(files_dict)
        cache_key = self._get_cache_key(instance_id, file_source, prompt_style, files_hash)
        cache_file = self.cache_dir / f"{cache_key}.pkl"
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(prompt, f)
        except Exception as e:
            logger.warning(f"Failed to cache for {instance_id}: {e}")


class SmartFileSelector:
    """Smart file selection for Android projects"""
    
    # Android-specific file patterns and weights
    ANDROID_FILE_PATTERNS = {
        # High priority - likely to contain business logic
        r'.*/(ui|fragment|activity|service|receiver)/.*\.java$': 3.0,
        r'.*/(ui|fragment|activity|service|receiver)/.*\.kt$': 3.0,
        r'.*/model/.*\.java$': 2.8,
        r'.*/model/.*\.kt$': 2.8,
        r'.*/storage/.*\.java$': 2.5,
        r'.*/storage/.*\.kt$': 2.5,
        r'.*/adapter/.*\.java$': 2.3,
        r'.*/adapter/.*\.kt$': 2.3,
        
        # Medium priority - support files
        r'.*/util/.*\.java$': 2.0,
        r'.*/util/.*\.kt$': 2.0,
        r'.*/event/.*\.java$': 1.8,
        r'.*/event/.*\.kt$': 1.8,
        r'.*/preferences/.*\.java$': 1.8,
        r'.*/preferences/.*\.kt$': 1.8,
        
        # Lower priority but still relevant
        r'.*\.xml$': 1.5,  # Layouts, manifests, etc.
        r'.*\.gradle$': 1.3,
        r'.*\.properties$': 1.0,
        
        # Very low priority
        r'.*/test/.*': 0.5,
        r'.*/androidTest/.*': 0.5,
        r'.*/(generated|build)/.*': 0.1,
    }
    
    def __init__(self):
        self.compiled_patterns = [(re.compile(pattern), weight) 
                                for pattern, weight in self.ANDROID_FILE_PATTERNS.items()]
    
    def get_file_relevance_score(self, filepath: str, issue_text: str = "") -> float:
        """Calculate relevance score for a file"""
        score = 1.0  # Base score
        
        # Pattern-based scoring
        for pattern, weight in self.compiled_patterns:
            if pattern.match(filepath):
                score = max(score, weight)
        
        # Issue-based scoring boost
        if issue_text:
            filename = Path(filepath).stem.lower()
            issue_lower = issue_text.lower()
            
            # Boost if filename mentioned in issue
            if filename in issue_lower:
                score *= 2.0
            
            # Boost for key Android components mentioned in issue
            android_keywords = AndroidProjectConfig.ANDROID_KEYWORDS
            
            for keyword in android_keywords:
                if keyword in issue_lower and keyword in filepath.lower():
                    score *= 1.5
                    break
        
        return score
    
    # def select_files(self, all_files: Dict[str, str], oracle_files: Set[str], 
    #                 issue_text: str = "", max_files: int = 20) -> Dict[str, str]:
    #     """Smart file selection prioritizing relevant files"""
        
    #     # Always include oracle files (files that are actually changed)
    #     selected_files = {}
    #     file_scores = []
        
    #     # Add oracle files first
    #     for filepath in oracle_files:
    #         if filepath in all_files:
    #             selected_files[filepath] = all_files[filepath]
        
    #     # Score remaining files
    #     for filepath, content in all_files.items():
    #         if filepath not in oracle_files:
    #             score = self.get_file_relevance_score(filepath, issue_text)
    #             file_scores.append((score, filepath, content))
        
    #     # Sort by score and take top files
    #     file_scores.sort(reverse=True)
    #     remaining_slots = max_files - len(selected_files)
        
    #     for score, filepath, content in file_scores[:remaining_slots]:
    #         selected_files[filepath] = content
            
    #     logger.info(f"Selected {len(selected_files)} files "
    #                f"({len(oracle_files)} oracle + {len(selected_files) - len(oracle_files)} additional)")
        
    #     return selected_files

    def select_files(self, all_files: Dict[str, str], oracle_files: Set[str], 
                    issue_text: str = "", max_files: int = 20) -> Dict[str, str]:
        """Smart file selection prioritizing relevant files"""

        logger.info(f"=== DEBUG INFO ===")
        logger.info(f"Total files in repository: {len(all_files)}")
        logger.info(f"Oracle files expected: {len(oracle_files)}")


         # DEBUG: Show sample of actual files in repo
        sample_files = list(all_files.keys())[:10]
        logger.info(f"Sample repo files: {sample_files}")


        # DEBUG: Show sample of oracle files being looked for
        sample_oracle = list(oracle_files)
        logger.info(f"Sample oracle files: {sample_oracle}")
            
        selected_files = {}
        file_scores = []
        
        # Add oracle files that actually exist
        oracle_files_found = 0
        oracle_files_missing = []
        
        for filepath in oracle_files:
            if filepath in all_files:
                selected_files[filepath] = all_files[filepath]
                oracle_files_found += 1
            else:
                oracle_files_missing.append(filepath)

        # DEBUG: Show path comparison
        if oracle_files_missing and all_files:
            logger.info(f"=== PATH ANALYSIS ===")
            first_missing = oracle_files_missing[0]
            first_actual = list(all_files.keys())[0]
            logger.info(f"Missing oracle: {first_missing}")
            logger.info(f"Actual file:    {first_actual}")
            logger.info(f"=== END DEBUG ===")

        # Log missing oracle files if any (but limit to first 3 to avoid spam)
        if oracle_files_missing:
            logger.warning(f"Oracle files not found: {len(oracle_files_missing)} missing")
            if len(oracle_files_missing) <= 3:
                logger.warning(f"Missing files: {oracle_files_missing}")
            else:
                logger.warning(f"First 3 missing: {oracle_files_missing[:3]}")
        
        # Score remaining files
        for filepath, content in all_files.items():
            if filepath not in oracle_files:
                score = self.get_file_relevance_score(filepath, issue_text)
                file_scores.append((score, filepath, content))
        
        # Sort by score and take top files
        file_scores.sort(reverse=True)
        remaining_slots = max_files - len(selected_files)
        
        additional_files_added = 0
        for score, filepath, content in file_scores[:remaining_slots]:
            selected_files[filepath] = content
            additional_files_added += 1
        
        logger.info(f"Selected {len(selected_files)} files "
                    f"({oracle_files_found}/{len(oracle_files)} oracle + "
                    f"{additional_files_added} additional)")
        
        return selected_files


class ContextChunker:
    """Handles chunking of large contexts"""
    
    def __init__(self, max_chunk_size: int = 50000):
        self.max_chunk_size = max_chunk_size
    
    def estimate_token_count(self, text: str) -> int:
        """Rough token estimation (4 chars per token average)"""
        return len(text) // 4
    
    def chunk_files_by_relevance(self, files_dict: Dict[str, str], 
                                oracle_files: Set[str]) -> List[Dict[str, str]]:
        """Split files into chunks, keeping oracle files in first chunk"""
        chunks = []
        current_chunk = {}
        current_size = 0
        
        # Always include oracle files in first chunk
        for filepath in oracle_files:
            if filepath in files_dict:
                content = files_dict[filepath]
                file_size = self.estimate_token_count(content)
                current_chunk[filepath] = content
                current_size += file_size
        
        # Add other files to chunks
        for filepath, content in files_dict.items():
            if filepath not in oracle_files:
                file_size = self.estimate_token_count(content)
                
                # If adding this file exceeds chunk size, start new chunk
                if current_size + file_size > self.max_chunk_size and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = {}
                    current_size = 0
                
                current_chunk[filepath] = content
                current_size += file_size
        
        # Add final chunk
        if current_chunk:
            chunks.append(current_chunk)
        
        logger.info(f"Split context into {len(chunks)} chunks")
        return chunks
