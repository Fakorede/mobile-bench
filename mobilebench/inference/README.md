##


### Key Features:

- Multiple prompt styles for different training approaches
- Context management (token limits, file selection)
- Resumable processing with progress files
- HuggingFace integration for easy dataset sharing
- Flexible file sources (oracle, retrieval, all files)

### Input:
Task instances with:

- Problem statements
- Code repositories
- Solution patches

### Output:
Training datasets with:

- `text`: Formatted prompt with problem + code context
- `patch`: Target solution in patch format

### Usage

<!-- ```shell
python create_prompt_dataset.py \
  --dataset_name_or_path ./my_task_instances \
  --splits train test \
  --output_dir ./training_data \
  --prompt_style style-3 \
  --file_source oracle
``` -->

```shell
python create_evaluation_prompts.py \
  data/tasks/ \
  data/prompts/ \
  --prompt_style style-3 \
  --file_source oracle
```


### Workflow

```
Raw Task Instances → create_instance.py → Formatted Prompts → create_prompt_dataset.py → Training Dataset
```

