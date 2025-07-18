##


### Usage

```shell
python collect_github_data.py \
    --repos org/repo, org/repo \
    --path_prs '<path to folder to save PRs to>' \
    --path_tasks '<path to folder to save tasks to>'
```

### Workflow

```shell
1. fetch_pull_requests.py → PR data
2. build_task_instances.py → Task instances
```