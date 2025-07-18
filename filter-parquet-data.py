import pandas as pd


def filter_and_save(parquet_file, csv_file, filter_conditions=None):
    """
    Read a parquet file, apply optional filters, retain only unique records based on
    pr_number, and save to CSV while retaining all columns except the patch column
    
    Parameters:
    -----------
    parquet_file : str
        Path to the input parquet file
    csv_file : str
        Path where the filtered CSV should be saved
    filter_conditions : dict, optional
        Dictionary of column names and values to filter by
    """
    # Read the parquet file
    df = pd.read_parquet(parquet_file)
    
    # Print original dataframe info
    print(f"Original data: {len(df)} rows, {len(df.columns)} columns")
    
    # Apply filters if provided
    if filter_conditions:
        for column, value in filter_conditions.items():
            if column in df.columns:
                if isinstance(value, (int, float)):
                    # For numeric values, filter where column equals the value
                    df = df[df[column] == value]
                elif isinstance(value, str):
                    # For string values, filter where column contains the value
                    df = df[df[column].str.contains(value, na=False)]
                elif isinstance(value, tuple) and len(value) == 2:
                    # For range values (min, max), filter within range
                    min_val, max_val = value
                    df = df[(df[column] >= min_val) & (df[column] <= max_val)]
    
    # Drop duplicates based on pr_number - deduplication
    if 'pr_number' in df.columns:
        duplicate_count = len(df) - len(df['pr_number'].unique())
        print(f"Found {duplicate_count} duplicate rows based on pr_number")
        
        # Keep only the first occurrence of each pr_number
        df = df.drop_duplicates(subset=['pr_number'], keep='first')
        print(f"After removing duplicates: {len(df)} rows")
    else:
        print("Warning: 'pr_number' column not found, cannot deduplicate")
    
    # Remove the patch column if it exists
    if 'patch' in df.columns:
        df = df.drop(columns=['patch'])
    
    # Add empty columns for fail_to_pass and pass_to_pass (if they don't already exist)
    if 'fail_to_pass' not in df.columns:
        df['fail_to_pass'] = ""
    if 'pass_to_pass' not in df.columns:
        df['pass_to_pass'] = ""
    
    # Print filtered dataframe info
    print(f"Final data: {len(df)} rows, {len(df.columns)} columns")
    
    # Save to CSV
    df.to_csv(csv_file, index=False)
    print(f"Data successfully saved to {csv_file}")


if __name__ == "__main__":
    filter_and_save(
        parquet_file="test_patches_after_2024.parquet",
        csv_file="repo_tests1.csv",
        filter_conditions={'repo_full_name': 'duckduckgo/Android'}
    )