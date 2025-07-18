#!/usr/bin/env python3

import json
import os

# Create sample data directory
os.makedirs('sample_data', exist_ok=True)

# Sample instance data
sample_instances = [
    {
        "instance_id": "sample_android_1",
        "repo": "https://github.com/bitwarden/android.git",
        "base_commit": "main",
        "test_commands": ["./gradlew test"],
        "PASS_TO_PASS": ["com.bitwarden.ExampleTest::testExample"],
        "FAIL_TO_PASS": [],
        "issue_description": "Sample Android issue",
        "metadata": {"complexity": "low"}
    },
    {
        "instance_id": "sample_android_2", 
        "repo": "https://github.com/example/android-app.git",
        "base_commit": "develop",
        "test_commands": ["./gradlew testDebugUnitTest"],
        "PASS_TO_PASS": [],
        "FAIL_TO_PASS": ["com.example.FailingTest::testShouldPass"],
        "issue_description": "Another sample Android issue",
        "metadata": {"complexity": "medium"}
    }
]

# Sample predictions
sample_predictions = [
    {
        "instance_id": "sample_android_1",
        "model_name_or_path": "example_model",
        "patch": '''diff --git a/app/src/main/java/Example.java b/app/src/main/java/Example.java
index 1234567..abcdefg 100644
--- a/app/src/main/java/Example.java
+++ b/app/src/main/java/Example.java
@@ -10,7 +10,7 @@ public class Example {
     }
     
     public String getMessage() {
-        return "Hello World";
+        return "Hello Mobile-Bench";
     }
 }'''
    },
    {
        "instance_id": "sample_android_2",
        "model_name_or_path": "example_model", 
        "patch": '''diff --git a/app/src/test/java/ExampleTest.java b/app/src/test/java/ExampleTest.java
index 1234567..abcdefg 100644
--- a/app/src/test/java/ExampleTest.java
+++ b/app/src/test/java/ExampleTest.java
@@ -15,6 +15,6 @@ public class ExampleTest {
     @Test
     public void testExample() {
-        assertEquals("wrong", getValue());
+        assertEquals("correct", getValue());
     }
 }'''
    }
]

# Save sample data
with open('sample_data/instances.jsonl', 'w') as f:
    for instance in sample_instances:
        f.write(json.dumps(instance) + '\n')

with open('sample_data/predictions.jsonl', 'w') as f:
    for prediction in sample_predictions:
        f.write(json.dumps(prediction) + '\n')

print("Sample data created in ./sample_data/")
print("- instances.jsonl: Sample test instances")
print("- predictions.jsonl: Sample model predictions")
