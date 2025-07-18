"""
Usage: python3 filter_passing_builds.py 2024/Bitwarden-repo_tests.csv
"""
import pandas as pd
import json
import sys
import os

def filter_csv_to_json(input_csv_path):
    """
    Read CSV file, filter out instances with failing builds, and write successful instances to JSON.
    
    Args:
        input_csv_path (str): Path to the input CSV file
    """
    try:
        # Read the CSV file
        df = pd.read_csv(input_csv_path)
        
        # Define the failure message to filter out
        failure_message = "Gradle build failed and test couldn't run"
        
        # Filter out instances where either fail_to_pass or pass_to_pass contains the failure message
        successful_instances = df[
            (~df['fail_to_pass'].astype(str).str.contains(failure_message, na=False)) &
            (~df['pass_to_pass'].astype(str).str.contains(failure_message, na=False))
        ]
        
        # Select only the required columns for output
        output_columns = [
            'repo_full_name', 
            'pr_number', 
            'merge_commit_sha', 
            'head_ref', 
            'head_sha', 
            'base_ref', 
            'base_sha'
        ]
        
        # Extract the required data
        filtered_data = successful_instances[output_columns].to_dict('records')
        
        # Generate output filename based on input filename
        base_name = os.path.splitext(os.path.basename(input_csv_path))[0]
        output_json_path = f"{base_name}.json"
        
        # Write to JSON file
        with open(output_json_path, 'w', encoding='utf-8') as json_file:
            json.dump(filtered_data, json_file, indent=2, ensure_ascii=False)
        
        # Print summary
        total_instances = len(df)
        successful_instances_count = len(filtered_data)
        filtered_out_count = total_instances - successful_instances_count
        
        print(f"Processing completed successfully!")
        print(f"Total instances in CSV: {total_instances}")
        print(f"Instances with failing builds filtered out: {filtered_out_count}")
        print(f"Successful instances written to JSON: {successful_instances_count}")
        print(f"Output file: {output_json_path}")
        
    except FileNotFoundError:
        print(f"Error: Could not find the file '{input_csv_path}'")
        sys.exit(1)
    except KeyError as e:
        print(f"Error: Missing required column {e} in the CSV file")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # Check if filename is provided as command line argument
    if len(sys.argv) != 2:
        print("Usage: python script.py <input_csv_file>")
        print("Example: python script.py data.csv")
        sys.exit(1)
    
    input_file = sys.argv[1]
    filter_csv_to_json(input_file)