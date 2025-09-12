#!/usr/bin/env python3
# create_instance.py

"""
Purpose: Processing library for converting raw task instances into formatted prompts for models evaluation
Input: Raw task instances from processed github data
Output: 
"""

import json
import logging
import os
import traceback
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unidiff
from tqdm.auto import tqdm

from tokenize_dataset import TOKENIZER_FUNCS

from utils import (
    AutoContextManager,
    ingest_directory_contents,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PATCH_EXAMPLE = """--- a/app/src/main/java/de/danoeh/antennapod/ui/swipeactions/RemoveFromHistorySwipeAction.java
+++ b/app/src/main/java/de/danoeh/antennapod/ui/swipeactions/RemoveFromHistorySwipeAction.java
@@ -38,10 +38,11 @@ public class RemoveFromHistorySwipeAction implements SwipeAction {
     @Override
     public void performAction(FeedItem item, Fragment fragment, FeedItemFilter filter) {
-        Date playbackCompletionDate = item.getMedia().getPlaybackCompletionDate();
+        Date lastPlayedTimeHistory = item.getMedia().getLastPlayedTimeHistory();
         DBWriter.deleteFromPlaybackHistory(item);
         EventBus.getDefault().post(new MessageEvent(fragment.getString(R.string.removed_history_label),
-            context -> DBWriter.addItemToPlaybackHistory(item.getMedia(), playbackCompletionDate)),
+            context -> DBWriter.addItemToPlaybackHistory(item.getMedia(), lastPlayedTimeHistory)),
             fragment.getString(R.string.undo)));
     }
 }"""


FULL_GENERATION_EXAMPLE = """[start of app/src/main/java/de/danoeh/antennapod/ui/swipeactions/RemoveFromHistorySwipeAction.java]
package de.danoeh.antennapod.ui.swipeactions;

import android.content.Context;
import androidx.fragment.app.Fragment;
import de.danoeh.antennapod.R;
import de.danoeh.antennapod.model.feed.FeedItem;
import de.danoeh.antennapod.model.feed.FeedItemFilter;
import de.danoeh.antennapod.storage.database.DBWriter;
import de.danoeh.antennapod.event.MessageEvent;
import org.greenrobot.eventbus.EventBus;
import java.util.Date;

public class RemoveFromHistorySwipeAction implements SwipeAction {
    
    @Override
    public int getActionIcon() {
        return R.drawable.ic_history_remove;
    }
    
    @Override
    public int getActionColor() {
        return R.attr.icon_purple;
    }
    
    @Override
    public String getTitle(Context context) {
        return context.getString(R.string.remove_history_label);
    }
    
    @Override
    public void performAction(FeedItem item, Fragment fragment, FeedItemFilter filter) {
        Date lastPlayedTimeHistory = item.getMedia().getLastPlayedTimeHistory();
        DBWriter.deleteFromPlaybackHistory(item);
        EventBus.getDefault().post(new MessageEvent(fragment.getString(R.string.removed_history_label),
            context -> DBWriter.addItemToPlaybackHistory(item.getMedia(), lastPlayedTimeHistory)),
            fragment.getString(R.string.undo)));
    }
    
    @Override
    public boolean willRemove(FeedItemFilter filter, FeedItem item) {
        return true;
    }
}
[end of app/src/main/java/de/danoeh/antennapod/ui/swipeactions/RemoveFromHistorySwipeAction.java]"""


# Utility Functions
# Adds line numbers 
def add_lines_list(content):
    content_with_lines = list()
    for ix, line in enumerate(content.split("\n"), start=1):
        content_with_lines.append(f"{ix} {line}")
    return content_with_lines


def add_lines(content):
    return "\n".join(add_lines_list(content))


# Formats code files with [start of file] markers and optional line numbers
def make_code_text(files_dict, add_line_numbers=True):
    all_text = ""
    for filename, contents in sorted(files_dict.items()):
        all_text += f"[start of {filename}]\n"
        if add_line_numbers:
            all_text += add_lines(contents)
        else:
            all_text += contents
        all_text += f"\n[end of {filename}]\n"
    return all_text.strip("\n")


# Shows only ±15 lines around edited sections instead of full files - prompt_style_2_edits_only
def make_code_text_edits_only(files_dict, patch, add_line_numbers=True):
    files = dict()
    patch = unidiff.PatchSet(patch)
    for patched_file in patch:
        source_file = patched_file.source_file.split("a/", 1)[-1]
        files[source_file] = list()
        for hunk in patched_file:
            start = hunk.source_start - 15
            end = start + hunk.source_length + 15
            files[source_file].append((start, end))
    all_text = ""
    for filename, content in files_dict.items():
        all_text += f"[start of {filename}]\n"
        content_with_lines = add_lines_list(content)
        for start, end in files[filename]:
            if start > 0:
                all_text += "...\n"
            all_text += "\n".join(content_with_lines[start:end])
            all_text += "\n"
            if end < len(content_with_lines):
                all_text += "...\n"
        all_text = all_text.strip("\n")
        all_text += f"\n[end of {filename}]\n"
    return all_text.strip("\n")


# Prompt Generation Functions
# Creates prompt with issue + full code + patch example + instructions
def prompt_style_2(instance):
    premise = "You will be provided with a partial code base and an issue statement explaining a problem to resolve."
    readmes_text = make_code_text(instance["readmes"])
    code_text = make_code_text(instance["file_contents"])
    instructions = (
        "I need you to solve this issue by generating a single patch file that I can apply "
        + "directly to this repository using git apply. Please respond with a single patch "
        + "file in the following format."
    )
    problem_statement = instance["problem_statement"]
    final_text = [
        premise,
        "<issue>",
        problem_statement,
        "</issue>",
        "<code>",
        readmes_text,
        code_text,
        "</code>",
        instructions,
        "<patch>",
        PATCH_EXAMPLE,
        "</patch>",
    ]
    final_text = "\n".join(final_text)
    return final_text


# Same as style-2 but shows only edited code sections
def prompt_style_2_edits_only(instance):
    premise = "You will be provided with a partial code base and an issue statement explaining a problem to resolve."
    readmes_text = make_code_text(instance["readmes"])
    code_text = make_code_text_edits_only(instance["file_contents"], instance["patch"])
    instructions = (
        "I need you to solve this issue by generating a single patch file that I can apply "
        + "directly to this repository using git apply. Please respond with a single patch "
        + "file in the following format."
    )
    problem_statement = instance["problem_statement"]
    final_text = [
        premise,
        "<issue>",
        problem_statement,
        "</issue>",
        "<code>",
        readmes_text,
        code_text,
        "</code>",
        instructions,
        "<patch>",
        PATCH_EXAMPLE,
        "</patch>",
    ]
    final_text = "\n".join(final_text)
    return final_text


# Similar to style-2 but with clearer instructions and formatting
def prompt_style_3(instance):
    premise = "You will be provided with a partial code base and an issue statement explaining a problem to resolve."
    readmes_text = make_code_text(instance["readmes"])
    code_text = make_code_text(instance["file_contents"]) # <-- here
    example_explanation = (
        "Here is an example of a patch file. It consists of changes to the code base. "
        + "It specifies the file names, the line numbers of each change, and the removed and added lines. "
        + "A single patch file can contain changes to multiple files."
    )
    final_instruction = (
        "I need you to solve the provided issue by generating a single patch file in proper unified diff format that be "
        + "applied directly to this repository using git apply. Please respond with a single patch "
        + "file in the format shown above. Note: You should only modify the files in the provided code base, "
        + "you can change as many files as you like to resolve the issue. Do not create new files."
    )
    problem_statement = instance["problem_statement"]
    final_text = [
        premise,
        "<issue>",
        problem_statement,
        "</issue>",
        "",
        "<code>",
        readmes_text,
        code_text,
        "</code>",
        "",
        example_explanation,
        "<patch>",
        PATCH_EXAMPLE,
        "</patch>",
        "",
        final_instruction,
        "Respond below:",
    ]
    final_text = "\n".join(final_text)
    return final_text


def full_file_gen(instance):
    premise = "You will be provided with a partial code base and an issue statement explaining a problem to resolve."
    readmes_text = make_code_text(instance["readmes"], add_line_numbers=False)
    code_text = make_code_text(instance["file_contents"], add_line_numbers=False)
    instructions = (
        "I need you to solve this issue by regenerating the full files in the code base that you would like to change. "
        + "You can change as many files as you like. "
        + "Please respond with a list of files and their revised contents in the following format."
    )
    problem_statement = instance["problem_statement"]
    final_text = [
        premise,
        "<issue>",
        problem_statement,
        "</issue>",
        "<code>",
        readmes_text,
        code_text,
        "</code>",
        instructions,
        "<example>",
        FULL_GENERATION_EXAMPLE,
        "</example>",
    ]
    final_text = "\n".join(final_text)
    return final_text


# File Processing Functions
# Reads multiple files from disk into a dictionary
def ingest_files(filenames): # <-- here
    files_dict = dict()
    for filename in filenames:
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read()
            files_dict[filename] = content
        except UnicodeDecodeError:
            # Handle binary files
            files_dict[filename] = f"<BINARY FILE: {filename}>"
    return files_dict


PROMPT_FUNCTIONS = {
    "style-2": prompt_style_2,
    "style-3": prompt_style_3, # recommended
    "full_file_gen": full_file_gen,
    "style-2-edits-only": prompt_style_2_edits_only,
}


# BM-25 file retrieval
def add_retrieval_results(input_instances, retrieval_file, k, file_source):
    """
    Adds retrieval results to input_instances in-place
    """
    retrieval_results_path = Path(retrieval_file)
    assert retrieval_results_path.exists(), (
        f"Retrieval results not found at {retrieval_results_path}"
    )
    retrieval_results = [json.loads(line) for line in open(retrieval_results_path)]
    retrieval_results = {x["instance_id"]: x["hits"] for x in retrieval_results}
    for instance_id, instance in tqdm(
        input_instances.items(),
        total=len(input_instances),
        desc="Adding retrieval results",
    ):
        try:
            instance["hits"] = retrieval_results[instance_id][:k]
        except KeyError:
            logger.warning(f"Instance {instance_id} not found in retrieval results")
            instance["hits"] = list()


# Extracts which files are changed in the solution patch
def get_oracle_filenames(instance):
    """
    Returns the filenames that are changed in the patch
    """
    source_files = {
        patch_file.source_file.split("a/", 1)[-1]
        for patch_file in unidiff.PatchSet(instance["patch"])
    }
    gold_docs = set()
    for source_file in source_files:
        gold_docs.add(source_file)
    return gold_docs


# Main Processing Function
def add_text_inputs(
    instances,
    retrieval_file,
    k,
    prompt_style,
    file_source,
    max_context_len=None,
    tokenizer_name=None,
    verbose=False,
    progress_file=None,
) -> None:
    """Process instances and save results to progress file.

    Args:
    - instances: dictionary with unprocessed input instances
    - retrieval_file: if using retrieval method for file_contents, specify retrieval_file
    - k: if using retrieval, specifies the maximum number of files to include
    - prompt_style: specify the function to generate instructions and prompt
    - file_source: where to collect file_contents (e.g. oracle or bm25)
    - verbose: set ContextManager verbose to True
    - progress_file: required, path to save processed instances
    """
    assert progress_file is not None, "progress_file is required"

    # Create progress file directory if it doesn't exist
    progress_path = Path(progress_file)
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    # Load already processed instances
    processed_ids = set()
    file_exists = os.path.exists(progress_file)

    if file_exists:
        with open(progress_file) as f:
            for line in f:
                instance = json.loads(line)
                processed_ids.add(instance["instance_id"])
        logger.info(f"Found {len(processed_ids)} already processed instances")
        progress_file_handle = open(progress_file, "a")
    else:
        progress_file_handle = open(progress_file, "w")

    try:
        if max_context_len is not None:
            assert tokenizer_name is not None, (
                "Must specify tokenizer_name if using max_context_len"
            )
            tokenizer, tokenizer_func = TOKENIZER_FUNCS[tokenizer_name]

        # Add retrieval results if needed
        if file_source in {"bm25"}:
            instances = deepcopy(instances)
            add_retrieval_results(instances, retrieval_file, k, file_source)

        # Filter out already processed instances
        instances_to_process = {
            k: v for k, v in instances.items() if k not in processed_ids
        }
        logger.info(f"Processing {len(instances_to_process)} instances")

        orig_dir = os.getcwd()
        with TemporaryDirectory(
            dir="/scratch" if os.path.exists("/scratch") else "/tmp"
        ) as root_dir:
            for instance_id, instance in tqdm(
                instances_to_process.items(),
                total=len(instances_to_process),
                desc="Processing instances",
            ):
                try:
                    with AutoContextManager(instance, root_dir, verbose=verbose) as cm:
                        # Process instance
                        processed_instance = deepcopy(instance)

                        # Add readmes
                        readmes = cm.get_readme_files()
                        processed_instance["readmes"] = ingest_files(readmes)

                        # Handle file contents based on configuration
                        if max_context_len is not None: # <-- here
                            processed_instance["file_contents"] = dict()
                            base_text_inputs = PROMPT_FUNCTIONS[prompt_style](
                                processed_instance
                            )
                            base_text_input_length = len(
                                tokenizer_func(base_text_inputs, tokenizer)
                            )

                        if file_source == "oracle": # <-- here
                            processed_instance["file_contents"] = ingest_files(
                                get_oracle_filenames(processed_instance)
                            )
                        elif file_source == "bm25":
                            processed_instance["file_contents"] = ingest_files(
                                [x["docid"] for x in processed_instance["hits"]]
                            )
                        elif file_source == "all":
                            processed_instance["file_contents"] = (
                                ingest_directory_contents(cm.repo_path)
                            )
                        elif file_source == "none":
                            processed_instance["file_contents"] = dict()
                        else:
                            raise ValueError(f"Invalid file source {file_source}")

                        # Handle context length limits
                        if max_context_len is not None:
                            cur_input_len = base_text_input_length
                            include_files = []
                            for filename in [
                                x["docid"] for x in processed_instance["hits"]
                            ]:
                                content = make_code_text(
                                    {
                                        filename: processed_instance["file_contents"][
                                            filename
                                        ]
                                    }
                                )
                                if tokenizer_name == "llama":
                                    tokens = tokenizer_func("\n" + content, tokenizer)
                                    idx = tokens.index(13)
                                    tokens = tokens[idx + 1 :]
                                else:
                                    tokens = tokenizer_func(content, tokenizer)
                                if cur_input_len + len(tokens) < max_context_len:
                                    include_files.append(filename)
                                    cur_input_len += len(tokens)
                            processed_instance["file_contents"] = {
                                filename: processed_instance["file_contents"][filename]
                                for filename in include_files
                            }

                        # Generate final text inputs
                        processed_instance["prompt"] = PROMPT_FUNCTIONS[ # <-- here
                            prompt_style
                        ](processed_instance)

                        # Save to progress file
                        progress_file_handle.write(
                            json.dumps(processed_instance) + "\n"
                        )
                        progress_file_handle.flush()

                except Exception as e:
                    print(f"Failed on instance {instance_id}", e)
                    traceback.print_exc()
                    # Save failed instance
                    failed_instance = {**instance, "prompt": None}
                    progress_file_handle.write(json.dumps(failed_instance) + "\n")
                    progress_file_handle.flush()
                finally:
                    os.chdir(orig_dir)
        os.chdir(orig_dir)
    finally:
        progress_file_handle.close()
