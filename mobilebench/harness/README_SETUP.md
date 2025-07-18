# Mobile-Bench Setup Complete

## Quick Start

1. **Activate the environment:**
   ```bash
   source venv/bin/activate
   ```

2. **Create sample data (optional):**
   ```bash
   python3 create_sample_data.py
   ```

3. **Run health check:**
   ```bash
   ./health_check.sh
   ```

4. **Run example evaluation:**
   ```bash
   ./run_example.sh
   ```

## Usage

### Basic Usage
```bash
python3 mobile_bench_evaluator.py \
    --dataset_path /path/to/instances.jsonl \
    --predictions_path /path/to/predictions.jsonl \
    --run_id my_evaluation_run
```

### Advanced Usage
```bash
python3 mobile_bench_evaluator.py \
    --dataset_path ./data/instances.jsonl \
    --predictions_path ./data/predictions.jsonl \
    --run_id detailed_run_$(date +%Y%m%d) \
    --max_workers 6 \
    --timeout 2400 \
    --log_level DEBUG \
    --report_dir ./custom_reports
```

## Configuration

Edit `mobile_bench_config.yaml` to customize:
- Docker settings
- Java version mappings
- Default test commands
- Logging configuration
- Report settings

## Maintenance

- **Health check:** `./health_check.sh`
- **Cleanup:** `./cleanup.sh`
- **Update Docker image:** `docker pull mingc/android-build-box:latest`

## Troubleshooting

1. **Docker issues:** Ensure Docker daemon is running
2. **Permission issues:** Check file permissions and user groups
3. **Memory issues:** Reduce max_workers or increase Docker memory limit
4. **Timeout issues:** Increase timeout value for complex projects

## File Structure

```
mobile-bench/
├── mobile_bench_evaluator.py     # Main evaluation script
├── mobile_bench_utils.py         # Utility functions
├── mobile_bench_test_spec.py     # Test specification handling
├── mobile_bench_grading.py       # Grading and evaluation logic
├── mobile_bench_config.yaml      # Configuration file
├── requirements.txt              # Python dependencies
├── venv/                         # Python virtual environment
├── mobile_bench_logs/            # Execution logs
├── mobile_bench_reports/         # Generated reports
├── mobile_bench_cache/           # Cache directory
├── test_specs/                   # Test specifications
└── sample_data/                  # Sample data for testing
```

## Support

For issues and questions:
1. Check the logs in `mobile_bench_logs/`
2. Run health check: `./health_check.sh`
3. Review the configuration: `mobile_bench_config.yaml`
