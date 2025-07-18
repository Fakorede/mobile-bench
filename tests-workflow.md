## Terminology

**PASS_TO_PASS**

Definition: Tests that should continue passing after applying the patch
Purpose: Ensures the patch doesn't break existing functionality (regression testing)
Example: ["com.bitwarden.AuthTest::testValidLogin", "com.bitwarden.CryptoTest::testEncryption"]

**FAIL_TO_PASS**

Definition: Tests that are currently failing but should start passing after applying the patch
Purpose: Validates that the patch actually fixes the intended issue
Example: ["com.bitwarden.BuggyFeatureTest::testBugFix"]


## Two Phases of Mobile-Bench Evaluation

### Phase 1: Ground Truth Collection (BEFORE model evaluation)

This is where `PASS_TO_PASS` and `FAIL_TO_PASS` would be established:
```python
# This happens BEFORE you run any model patches
# You run tests on the original buggy code to establish baseline

# 1. Checkout the base commit (buggy version)
git checkout base_commit

# 2. Run all tests and record which ones pass/fail
test_results = run_android_tests()

# 3. Identify the problematic tests based on the issue/PR
FAIL_TO_PASS = ["tests that are currently failing due to the bug"]
PASS_TO_PASS = ["tests that are currently passing and should stay passing"]

# 4. This becomes your "ground truth" for evaluation
```

### Phase 2: Model Evaluation (AFTER applying patches)

This is what you're currently doing:
```python
# This is what your mobile-bench harness does
# 1. Apply model-generated patch
# 2. Run tests 
# 3. Compare results against expected behavior (PASS_TO_PASS/FAIL_TO_PASS)
```



## Dataset Creation

```bash
# For each GitHub issue/PR:

# 1. Identify the issue
issue = "Bug: Authentication fails with special characters"

# 2. Checkout the buggy commit
git checkout buggy_commit

# 3. Run tests to establish baseline
baseline_results = run_all_tests()
# Result: 95 tests pass, 2 tests fail

# 4. Checkout the fix commit  
git checkout fix_commit

# 5. Run tests to see what changed
fix_results = run_all_tests()
# Result: 97 tests pass, 0 tests fail

# 6. Determine the expectations
FAIL_TO_PASS = tests_that_were_failing_but_now_pass(baseline_results, fix_results)
# ["AuthTest::testSpecialCharacters", "AuthTest::testUnicodePasswords"] 

PASS_TO_PASS = tests_that_should_stay_passing(baseline_results)
# ["AuthTest::testBasicLogin", "AuthTest::testValidation", ...93 other tests]

# 7. Create dataset entry
{
    "instance_id": "repo__issue-123",
    "base_commit": "buggy_commit", 
    "patch": "human_written_fix",  # The actual fix from the PR
    "FAIL_TO_PASS": ["AuthTest::testSpecialCharacters", "AuthTest::testUnicodePasswords"],
    "PASS_TO_PASS": ["AuthTest::testBasicLogin", "AuthTest::testValidation", ...]
}
```

### Prompts

Given a csv file which contains the results of running the android tests in a repo (this can be found in the project knowledge titled bitwarden-repo-tests.csv), provide a python script that is capable of doing the following:

1. Ignore instances where the tests failed to run.

2. Extract the instances that ran successfully in a JSONL file, but ensure the following:

- Ensure only one variant of the test suites is extracted, for example if the test suites run contain debug and release variants, consider only the debug variant.

- The FAIL_TO_PASS, PASS_TO_PASS fields should be an list of test cases where FAIL_TO_PASS will contain tests that were failing in the base commit tests results and now passing in the merge tests results, and PASS_TO_PASS will contain tests that should stay passing across both.

This should be in the example format:

FAIL_TO_PASS = ["AuthTest::testSpecialCharacters", "AuthTest::testUnicodePasswords"]
PASS_TO_PASS = ["AuthTest::testBasicLogin", "AuthTest::testValidation"]




python android_test_processor.py