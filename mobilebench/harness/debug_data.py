# Create a debug script: debug_data.py
import json

def debug_instances(dataset_path, predictions_path):
    """Debug the data format"""
    
    print("=== DEBUGGING MOBILE-BENCH DATA ===")
    
    # Load and inspect instances
    print(f"\n1. Loading instances from: {dataset_path}")
    try:
        if dataset_path.endswith('.jsonl'):
            instances = []
            with open(dataset_path, 'r') as f:
                for i, line in enumerate(f):
                    if line.strip():
                        instance = json.loads(line.strip())
                        instances.append(instance)
                        if i < 3:  # Show first 3 instances
                            print(f"\nInstance {i+1} keys: {list(instance.keys())}")
                            print(f"  instance_id: {instance.get('instance_id')}")
                            print(f"  repo: {instance.get('repo')}")
                            print(f"  base_commit: {instance.get('base_commit')}")
                            print(f"  PASS_TO_PASS: {instance.get('PASS_TO_PASS')}")
                            print(f"  FAIL_TO_PASS: {instance.get('FAIL_TO_PASS')}")
        else:
            with open(dataset_path, 'r') as f:
                instances = json.load(f)
                
        print(f"\nTotal instances: {len(instances)}")
        
    except Exception as e:
        print(f"Error loading instances: {e}")
        return
    
    # Load and inspect predictions
    print(f"\n2. Loading predictions from: {predictions_path}")
    try:
        predictions = {}
        if predictions_path.endswith('.jsonl'):
            with open(predictions_path, 'r') as f:
                for i, line in enumerate(f):
                    if line.strip():
                        pred = json.loads(line.strip())
                        predictions[pred['instance_id']] = pred
                        if i < 3:  # Show first 3 predictions
                            print(f"\nPrediction {i+1} keys: {list(pred.keys())}")
                            print(f"  instance_id: {pred.get('instance_id')}")
                            print(f"  patch: {pred.get('patch', '')[:100]}...")
        else:
            with open(predictions_path, 'r') as f:
                pred_data = json.load(f)
                if isinstance(pred_data, dict):
                    predictions = pred_data
                else:
                    predictions = {pred['instance_id']: pred for pred in pred_data}
                    
        print(f"\nTotal predictions: {len(predictions)}")
        
    except Exception as e:
        print(f"Error loading predictions: {e}")
        return
    
    # Check data consistency
    print(f"\n3. Data consistency check")
    instance_ids = set(instance['instance_id'] for instance in instances)
    prediction_ids = set(predictions.keys())
    
    missing_predictions = instance_ids - prediction_ids
    extra_predictions = prediction_ids - instance_ids
    
    print(f"Instances with predictions: {len(instance_ids & prediction_ids)}")
    print(f"Instances missing predictions: {len(missing_predictions)}")
    print(f"Extra predictions: {len(extra_predictions)}")
    
    if missing_predictions:
        print(f"First 5 missing predictions: {list(missing_predictions)[:5]}")
    
    # Check for problematic data
    print(f"\n4. Data quality check")
    problematic_instances = []
    
    for instance in instances[:10]:  # Check first 10
        issues = []
        if not instance.get('instance_id'):
            issues.append("missing instance_id")
        if not instance.get('repo'):
            issues.append("missing repo")
        if not instance.get('base_commit'):
            issues.append("missing base_commit")
            
        if issues:
            problematic_instances.append((instance.get('instance_id', 'unknown'), issues))
    
    if problematic_instances:
        print("Problematic instances found:")
        for instance_id, issues in problematic_instances:
            print(f"  {instance_id}: {', '.join(issues)}")
    else:
        print("No obvious data quality issues in first 10 instances")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python debug_data.py <dataset_path> <predictions_path>")
        sys.exit(1)
    
    debug_instances(sys.argv[1], sys.argv[2])