import pandas as pd
import sys

def compare_csv_files(file1_path, file2_path, output_path):
    """
    Compare two CSV files and create a new CSV with rows that have unique pr_number values.
    
    Args:
        file1_path (str): Path to the first CSV file
        file2_path (str): Path to the second CSV file
        output_path (str): Path where the output CSV will be saved
    """
    try:
        # Read both CSV files
        df1 = pd.read_csv(file1_path)
        df2 = pd.read_csv(file2_path)
        
        print(f"File 1 ({file1_path}): {len(df1)} rows")
        print(f"File 2 ({file2_path}): {len(df2)} rows")
        
        # Check if pr_number column exists in both files
        if 'pr_number' not in df1.columns or 'pr_number' not in df2.columns:
            print("Error: The 'pr_number' column doesn't exist in one or both files.")
            return False
        
        # Get sets of pr_numbers from both files
        pr_numbers1 = set(df1['pr_number'].astype(str))
        pr_numbers2 = set(df2['pr_number'].astype(str))
        
        # Find PR numbers unique to each file
        unique_in_file1 = pr_numbers1 - pr_numbers2
        unique_in_file2 = pr_numbers2 - pr_numbers1
        
        print(f"PR numbers unique to file 1: {len(unique_in_file1)}")
        print(f"PR numbers unique to file 2: {len(unique_in_file2)}")
        
        # Get rows with unique PR numbers
        unique_rows_from_file1 = df1[df1['pr_number'].astype(str).isin(unique_in_file1)]
        unique_rows_from_file2 = df2[df2['pr_number'].astype(str).isin(unique_in_file2)]
        
        print(f"Rows with unique PR numbers in file 1: {len(unique_rows_from_file1)}")
        print(f"Rows with unique PR numbers in file 2: {len(unique_rows_from_file2)}")
        
        # Combine the unique rows
        combined_unique_rows = pd.concat([unique_rows_from_file1, unique_rows_from_file2], ignore_index=True)
        
        print(f"Total combined unique rows: {len(combined_unique_rows)}")
        
        # Write the result to a new file
        combined_unique_rows.to_csv(output_path, index=False)
        
        print(f"Successfully wrote {len(combined_unique_rows)} unique rows to {output_path}")
        return True
    
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    # Default file paths
    file1_path = "repo_tests.csv"
    file2_path = "repo_tests1.csv"
    output_path = "repo_tests_unique_rows.csv"
    
    # Check for command line arguments
    if len(sys.argv) >= 4:
        file1_path = sys.argv[1]
        file2_path = sys.argv[2]
        output_path = sys.argv[3]
    
    compare_csv_files(file1_path, file2_path, output_path)