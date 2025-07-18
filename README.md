# android-test-automation

## Setup Instructions

```shell
# create a venv
python -m venv venv

# activate the venv
source venv/bin/activate

# install deps
pip install -r requirements.txt

```


create `.env`

GITHUB_TOKENS=


1. Install package

```shell
# install xmlstarlet
$ sudo apt install xmlstarlet
$ brew install xmlstarlet
```

2. Filter data

```shell
$ python filter-parquet-data.py
```


3. Run tests

```shell
$ ./script.sh repo_tests.csv 10 17
```