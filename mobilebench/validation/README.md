

```
output_directory/
├── final_validation_summary.json      # Complete results
├── validation_report.txt              # Human-readable report  
├── incremental_statistics.json        # Running statistics
├── validation_progress.json           # Resume tracking
├── validation_checkpoint.json         # Detailed checkpoints
└── [instance_id]/                     # Per-instance results
    ├── test_analysis.json
    ├── test_results_pre.json
    └── test_results_post.json
```


## Configuration



```python

# Configuration for instance ID normalization patterns
INSTANCE_ID_PATTERNS = {
    'thunderbird': 'thunderbird__thunderbird-android-',
    'AntennaPod': 'AntennaPod__AntennaPod-',
    'wordPress': 'wordpress-mobile__WordPress-Android-',
    'Tusky': 'tuskyapp__Tusky-',
    # Add more patterns as needed
}

```

## Basic Usage

```shell
# Run with your JSONL file
# Basic validation with auto-resume
python validator.py dataset.jsonl

# Resume after interruption (automatic)
python validator.py dataset.jsonl --output-dir previous_results

# Force restart from beginning
python validator.py dataset.jsonl --force-restart

# Validate specific instances with resume capability
python validator.py dataset.jsonl --instance-ids "6044" "6045"


THUNDERBIRD

failed
---------
6588 6873
7722 7931 8134 8999 9182


successful instances
-----------------------
9026 9423 9399 9332 9150 9279 9508 8813 8136 8329 9398 8259 8305 8889 8903 9469 8267 9428 9405 9161 9329 9386 9374 9351 9381 9322 9388 9362 9367 8602 8735 8147 8151 8541 9346 9448 9213 8272 8890 9341 9254 9011 9163 8904 6022 5881 6019 7113 6043 6030 7299 6482 6946 5989 6840 6693 6811 6190 7377 6555 7179 6049 6522 6507 6447 5926 5848 
8155 9414 9299 9179 6588 6600 6618 6624 6630 6762 6846 6987 7008 7180 7398 7403 7978 9128 9158 9241
6263 7489 5896 9268 5946 8547 5859 6435 5958 6280 7365 6424 6080 6546 6486 6256 6172 6360 7891 9028 9004



python validator.py ../../data/tasks/thunderbird-android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Thunderbird-SSG-3 \
  --instance-ids 9481 9360 9272 9209 9208 9207 9186 9182 9137 9130 9115 9104 9030 9010 8958 8906 8891 8846 8804 8382 8339 8306 8243 8176 8166 8130 8107 8099 8020 8014 7699 7569 7340 7292 6962 6561 6453 6335 6301 6158 6105 6082 6056 6051 6044 6041 5909 5872


Cannot locate tasks that match




ANTENNAPOD

python mobilebench/validation/validator.py data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod-SSG --exclude-instance-ids 7730 6652 6333 6029 5835 7713 7192 7176 7096 7011 6434 6403 6400 6384 6328 6286 6276 6236 6095 6041 6001 5726 7159

--instance-ids 5644 5679 5751 5872 5886 6057 6147 6153 6210 6266 6358 6420 6529 6530 6573 6659 6739 6808

python validator.py ../../data/tasks/AntennaPod-task-instances.jsonl --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/AntennaPod-SSG-batch --instance-ids 7060 7815 7581 7537 6739 7215 6529 6530 7098 6147 6057 5872 5644 6808 6659 6573 6358 6266 6210 6153 5886 5751


NEOSTUMBLER
python validator.py ../../data/tasks/NeoStumbler-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/NeoStumbler

TUSKY
python validator.py ../../data/tasks/Tusky-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/Tusky




WORDPRESS


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-1 \
  --instance-ids 21707 21610 21599 21584 21466 21457 21413 21287 21155 20947 \
  20940 20939 20925 20895 20891 20872 20861 20860 20846 20844 \
  20842 20839 20817 20802 20801 20791 20790 20781 20779 20769 \
  20763 20757 20756 20750 20747 20745 20732 20729 20728 20706 \
  20684 20682 20675 20668 20658 20656 20611 20608 20607 20606 \
  20603 20600 20596 20589 20586 20572 20571 20566 20564 20552 \
  20543 20526 20513 20480 20477 20465 20417 20414 20361 20251 \
  20243 20242 20216 20194 20186 20153 20137 20130 20125 20103 \
  20094 20090 20077 20074 20068 20057 19996 19993 19974 19971 \
  19940 19929 19911 19877 19860 19856 19848 19834 19823 19821


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-1-contd \
  --instance-ids 20153 20137 20130 20125 20103 \
  20094 20090 20077 20074 20068 20057 19996 19993 19974 19971 \
  19940 19929 19911 19877 19860 19856 19848 19834 19823 19821


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-2 \
  --instance-ids \
  19818 19810 19805 19804 19801 19790 19773 19771 19760 19745 19741 19730 19721 19715 19708 19679 19676 19662 19656 19637 19603 19602 19597 19593 19590 19589 19585 19577 19574 19570 19566 19565 19555 19547 19537 19527 19524 19513 19510 19509 19507
  
python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-2i-contd \
  --instance-ids \
  19498 19491 19485 19482 19469 19466 19462 19447 19429 \
  19425 19424 19416 19408 19387 19371 19367 19363 19360 19332 19304 19303 19283 19281 19262 19253 \
  19222 19205 19183 19178 19175 19135 19125 19116 19115 19112 19099 19095 19091 19059 18986 18967 \
  18962 18960 18959 18928 18925 18877 18818 18735 18686 18516 18487 18486 18479 18457 18438 18434 \
  18428 18409


python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-3 \
  --instance-ids \
  18390 18385 18377 18376 18364 18360 18346 18340 18337 18325 18322 18315 18310 18306 18295 18273 18271 18263 18244 18243 18240 18239 18234 18224 18191 18186 18172 18138 18130 18126 18118 18101 18089 18069 18058 18047 18043 18040 18037 18027 18016 17998 17997 17993 17982 17981 17980 17977 17970 17969 \
  17968 17967 17957 17949 17947 17946 17945 17932 17929 17920 17904 17890 17888 17872 17866 17856 17851 17848 17817 17816 17800 17799 17794 17787 17786 17781 17778 17776 17769 17768 17745 17742 17741 17723 17705 17703 17701 17699 17671 17627 17606 17604 17599 17585 17580 17547 17531 17527 17515 17496



Parser Issue:
19527

AST-based stubbing failed for wordpress-mobile__WordPress-Android-19507, continuing without stubs


AST-based stubbing failed for wordpress-mobile__WordPress-Android-19507, continuing without stubs

fatal: Unable to create '/workspace/.git/index.lock': File exists.


# python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  # --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-2 \
  # --instance-ids 20603 20600 20596 20589 20586 20572 20571 20566 20564 20552 \
  # 20543 20526 20513 20480 20477 20465 20417 20414 20361 20251 \
  # 20243 20242 20216 20194 20186 20153 20137 20130 20125 20103 \
  # 20094 20090 20077 20074 20068 20057 19996 19993 19974 19971 \
  # 19940 19929 19911 19877 19860 19856 19848 19834 19823 19821



python validator.py /home/researchuser/dev/mobile-bench/data/tasks/WordPress-Android-task-instances.jsonl \
  --output-dir /home/researchuser/dev/mobile-bench/data/validated-tasks/WordPress-20747 \
  --instance-ids 20747 --keep-containers


Build configuration file gradle.properties doesn't exist, follow README instructions


$ docker exec -it android-bench-wordpress-mobile--wordpress-android-20747 bash

$ docker exec -it -w / android-bench-wordpress-mobile--wordpress-android-20747 /bin/bash


cd /workspace_post
root@CSE2327PC07u:/workspace_post# ls
aars                       gradlew
build.gradle               gradlew.bat
codecov.yml                keystore
CODE-OF-CONDUCT.md         libs
CODEOWNERS                 LICENSE.md
config                     local-builds.gradle-example
CONTRIBUTING.md            local.properties
Dangerfile                 README.md
docs                       RELEASE-NOTES.txt
fastlane                   renovate.json
Gemfile                    settings.gradle
Gemfile.lock               tools
gradle                     version.properties
gradle.properties          WordPress
gradle.properties-example
root@CSE2327PC07u:/workspace_post# ls WordPress/
build                         jetpack_metadata
build.gradle                  metadata
google-services.json          proguard.cfg
google-services.json-example  src
gradle.properties
root@CSE2327PC07u:/workspace_post# cd /workspace
root@CSE2327PC07u:/workspace# ls
aars                       gradlew
build.gradle               gradlew.bat
codecov.yml                keystore
CODE-OF-CONDUCT.md         libs
CODEOWNERS                 LICENSE.md
config                     local-builds.gradle-example
CONTRIBUTING.md            README.md
Dangerfile                 RELEASE-NOTES.txt
docs                       renovate.json
fastlane                   settings.gradle
Gemfile                    tools
Gemfile.lock               version.properties
gradle                     WordPress
gradle.properties-example
root@CSE2327PC07u:/workspace# ls WordPress/
build.gradle                  metadata
google-services.json-example  proguard.cfg
jetpack_metadata              src



cat gradle.properties-example
# Project-wide Gradle settings.

# These are the default Gradle properties for WordPress-Android
# Feel free to tweak them for your machine (e.g. change -Xmx value below)
org.gradle.jvmargs=-Xmx6g -XX:+HeapDumpOnOutOfMemoryError
org.gradle.parallel=true
org.gradle.configureondemand=true
org.gradle.caching=true
org.gradle.configuration-cache=true

# WordPress-Android properties.

android.useAndroidX=true
android.enableJetifier=false

android.nonTransitiveRClass=true
android.nonFinalResIds=false
android.enableR8.fullMode=false

# For more details on what these properties do visit
# https://github.com/wordpress-mobile/WordPress-Android/blob/trunk/README.md

wp.oauth.app_id = wordpress
wp.oauth.app_secret = wordpress
wp.gcm.id = wordpress
wp.db_secret = wordpress
wp.app_license_key = wordpress
wp.zendesk.app_id=wordpress
wp.zendesk.domain=https://www.google.com/
wp.zendesk.oauth_client_id=wordpress
wp.docsbotai.id=wordpress
wp.reset_db_on_downgrade = false
wp.sentry.dsn=https://00000000000000000000000000000000@sentry.io/00000000
jp.sentry.dsn=https://00000000000000000000000000000000@sentry.io/00000000
wp.tenor.api_key=wordpress
wp.encrypted_logging_key=z0g+oVkqR4kWNUTxJfTozOZQjfXI7W9f6bD0uMJ5VkA=

# Optional: Needed for the end to end tests
wp.e2e.wp_com_user.email=e2eflowtestingmobile@example.com
wp.e2e.wp_com_user.password=mocked_password
wp.e2e.wp_com_user.site_address=e2eflowtestingmobile.wordpress.com
wp.e2e.wp_com_user.username=e2eflowtestingmobile
wp.e2e.wp_com_passwordless_user.email=e2eflowtestingmobile+passwordless@example.com
wp.e2e.self_hosted_user.username=e2eflowtestingmobile
wp.e2e.self_hosted_user.password=mocked_password
wp.e2e.self_hosted_user.site_address=127.0.0.1:8080

wp.e2e.signup_email=e2eflowsignuptestingmobile@example.com
wp.e2e.signup_username=e2eflowsignuptestingmobile
wp.e2e.signup_display_name=e2eflowsignuptestingmobile
wp.e2e.signup_password=mocked_password

# Dependency Analysis Plugin
dependency.analysis.android.ignored.variants=release,wordpressVanillaDebug,wordpressVanillaRelease,wordpressWasabiDebug,wordpressWasabiRelease,wordpressJalapenoRelease,jetpackVanillaDebug,jetpackVanillaRelease,jetpackWasabiDebug,jetpackWasabiRelease,jetpackJalapenoRelease

```





export OPENROUTER_API_KEY=xxxxxxxxx


https://spin.atomicobject.com/android-test-script/
https://andresand.medium.com/android-emulator-on-docker-container-f20c49b129ef



