import pandas as pd
import argparse
import os

def remove_duplicates(input_file, output_file=None):
    # Set default output filename if not provided
    if output_file is None:
        base_name = os.path.splitext(input_file)[0]
        output_file = f"{base_name}_no_duplicates.csv"
    
    # Read the CSV file
    df = pd.read_csv(input_file)
    
    # Print original number of rows
    original_count = len(df)
    print(f"Original file contains {original_count} rows.")
    
    # Remove duplicates, keeping the first occurrence of each pr_number
    df_no_duplicates = df.drop_duplicates(subset=['pr_number'], keep='first')
    
    # Print number of rows after removing duplicates
    new_count = len(df_no_duplicates)
    print(f"After removing duplicates: {new_count} rows.")
    print(f"Removed {original_count - new_count} duplicate rows.")
    
    # Save the deduplicated data to a new CSV file
    df_no_duplicates.to_csv(output_file, index=False)
    print(f"Deduplicated data saved to {output_file}")
    
    return df_no_duplicates

if __name__ == "__main__":
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(description='Remove duplicate rows from a CSV file based on pr_number column.')
    parser.add_argument('input_file', help='Path to the input CSV file')
    parser.add_argument('-o', '--output_file', help='Path to the output CSV file (optional)')
    
    args = parser.parse_args()
    
    # Call the function with provided arguments
    remove_duplicates(args.input_file, args.output_file)
    