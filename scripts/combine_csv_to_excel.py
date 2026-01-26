#!/usr/bin/env python3
"""
Script to combine multiple CSV comparison results into a single Excel workbook.

Usage:
    # Combine CSV files for a specific model (sonnet, gpt, qwen, gemini, etc.)
    python3 scripts/combine_csv_to_excel.py \
        --csv_dir data/evaluation \
        --specific qwen

    python3 scripts/combine_csv_to_excel.py \
        --csv_dir data/evaluation \
        --specific gpt

    # Or specify individual CSV files with custom output:
    python3 scripts/combine_csv_to_excel.py \
        --csv_files data/evaluation/antennapod/sonnet_patch_comparison_results.csv \
                    data/evaluation/zulip/sonnet_patch_comparison_results.csv \
        --output_file combined_results.xlsx
"""

import argparse
import sys
from pathlib import Path
from typing import List

try:
    import pandas as pd
except ImportError:
    print("Error: pandas library not found. Install with: pip install pandas openpyxl")
    sys.exit(1)

try:
    import openpyxl
except ImportError:
    print("Error: openpyxl library not found. Install with: pip install openpyxl")
    sys.exit(1)


def find_csv_files(csv_dir: Path, pattern: str = "**/*_patch_comparison_results.csv", specific: str = None) -> List[Path]:
    """
    Find all CSV files matching the pattern in the directory.

    Args:
        csv_dir: Directory to search
        pattern: Glob pattern to match CSV files
        specific: Model name to filter by (e.g., 'sonnet', 'gpt', 'qwen')

    Returns:
        List of CSV file paths
    """
    csv_files = list(csv_dir.glob(pattern))

    # Filter by specific model name if provided
    if specific:
        csv_files = [f for f in csv_files if specific.lower() in f.name.lower()]

    return sorted(csv_files)


def extract_repo_name(csv_path: Path) -> str:
    """
    Extract repository name from CSV file path.

    Args:
        csv_path: Path to CSV file

    Returns:
        Repository name
    """
    # Get the parent directory name (e.g., 'antennapod' from 'data/evaluation/antennapod/...')
    return csv_path.parent.name


def create_summary_sheet(all_data: dict) -> pd.DataFrame:
    """
    Create a summary sheet with aggregate statistics across all repos.

    Args:
        all_data: Dictionary mapping repo names to dataframes

    Returns:
        Summary dataframe
    """
    summary_rows = []

    for repo_name, df in all_data.items():
        if df.empty:
            continue

        summary_row = {
            'Repository': repo_name,
            'Total Instances': len(df),
            'Avg Gold Files': df['gold_file_count'].mean(),
            'Avg Model Files': df['model_file_count'].mean(),
            'Avg Overlap Count': df['overlap_count'].mean(),
            'Avg Overlap %': df['overlap_percentage'].mean(),
            'Instances with Overlap': (df['overlap_count'] > 0).sum(),
            'Instances without Overlap': (df['overlap_count'] == 0).sum(),
            'Max Overlap %': df['overlap_percentage'].max(),
            'Min Overlap %': df['overlap_percentage'].min()
        }
        summary_rows.append(summary_row)

    summary_df = pd.DataFrame(summary_rows)

    # Add totals row
    if not summary_df.empty:
        totals = {
            'Repository': 'TOTAL',
            'Total Instances': summary_df['Total Instances'].sum(),
            'Avg Gold Files': summary_df['Avg Gold Files'].mean(),
            'Avg Model Files': summary_df['Avg Model Files'].mean(),
            'Avg Overlap Count': summary_df['Avg Overlap Count'].mean(),
            'Avg Overlap %': summary_df['Avg Overlap %'].mean(),
            'Instances with Overlap': summary_df['Instances with Overlap'].sum(),
            'Instances without Overlap': summary_df['Instances without Overlap'].sum(),
            'Max Overlap %': summary_df['Max Overlap %'].max(),
            'Min Overlap %': summary_df['Min Overlap %'].min()
        }
        summary_df = pd.concat([summary_df, pd.DataFrame([totals])], ignore_index=True)

    return summary_df


def combine_csv_to_excel(csv_files: List[Path], output_file: Path, create_summary: bool = True):
    """
    Combine multiple CSV files into a single Excel workbook.

    Args:
        csv_files: List of CSV file paths
        output_file: Output Excel file path
        create_summary: Whether to create a summary sheet
    """
    if not csv_files:
        print("Error: No CSV files found")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV files to combine")

    # Load all CSV files
    all_data = {}
    for csv_file in csv_files:
        repo_name = extract_repo_name(csv_file)
        print(f"Loading {repo_name}: {csv_file}")

        try:
            df = pd.read_csv(csv_file)
            all_data[repo_name] = df
        except Exception as e:
            print(f"Warning: Failed to load {csv_file}: {e}")

    if not all_data:
        print("Error: No CSV files were successfully loaded")
        sys.exit(1)

    # Create Excel writer
    print(f"\nCreating Excel workbook: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Create summary sheet first (if requested)
        if create_summary:
            print("Creating summary sheet...")
            summary_df = create_summary_sheet(all_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

            # Format summary sheet
            worksheet = writer.sheets['Summary']

            # Auto-adjust column widths
            for idx, col in enumerate(summary_df.columns):
                max_length = max(
                    summary_df[col].astype(str).apply(len).max(),
                    len(col)
                )
                worksheet.column_dimensions[openpyxl.utils.get_column_letter(idx + 1)].width = min(max_length + 2, 50)

        # Write each repository's data to a separate sheet
        for repo_name, df in sorted(all_data.items()):
            # Truncate sheet name if too long (Excel has 31 char limit)
            sheet_name = repo_name[:31]
            print(f"Writing sheet: {sheet_name}")

            df.to_excel(writer, sheet_name=sheet_name, index=False)

            # Format worksheet
            worksheet = writer.sheets[sheet_name]

            # Auto-adjust column widths (with reasonable limits)
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).apply(len).max(),
                    len(col)
                )
                # Limit very wide columns (like file lists)
                worksheet.column_dimensions[openpyxl.utils.get_column_letter(idx + 1)].width = min(max_length + 2, 100)

    print(f"\n✓ Successfully created Excel workbook with {len(all_data)} sheets")
    if create_summary:
        print("  - Summary sheet with aggregate statistics")
    print(f"  - {len(all_data)} repository sheets")
    print(f"\nOutput file: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Combine multiple CSV comparison results into a single Excel workbook"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--csv_dir",
        type=Path,
        help="Directory containing CSV files (will search recursively)"
    )
    group.add_argument(
        "--csv_files",
        type=Path,
        nargs='+',
        help="List of specific CSV files to combine"
    )

    parser.add_argument(
        "--specific",
        type=str,
        help="Model name to filter CSV files by (e.g., 'sonnet', 'gpt', 'qwen', 'gemini'). "
             "Only CSV files containing this string in their name will be included. "
             "When used with --csv_dir, the output file will be automatically named "
             "as 'combined_patch_comparison_results-{model}.xlsx'"
    )
    parser.add_argument(
        "--output_file",
        type=Path,
        required=False,
        help="Path to output Excel file (optional when using --csv_dir with --specific)"
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="**/*_patch_comparison_results.csv",
        help="Glob pattern to match CSV files (only used with --csv_dir)"
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Don't create summary sheet"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.csv_files and not args.output_file:
        print("Error: --output_file is required when using --csv_files", file=sys.stderr)
        sys.exit(1)

    if args.csv_dir and args.specific and not args.output_file:
        # Auto-generate output file name based on specific model
        args.output_file = args.csv_dir / f"combined_patch_comparison_results-{args.specific}.xlsx"
    elif not args.output_file:
        print("Error: --output_file is required (or use --specific with --csv_dir for auto-naming)", file=sys.stderr)
        sys.exit(1)

    # Find CSV files
    if args.csv_dir:
        if not args.csv_dir.exists():
            print(f"Error: Directory not found: {args.csv_dir}", file=sys.stderr)
            sys.exit(1)
        csv_files = find_csv_files(args.csv_dir, args.pattern, args.specific)

        if args.specific:
            print(f"Filtering CSV files by model: {args.specific}")
    else:
        csv_files = args.csv_files
        # Validate that files exist
        for csv_file in csv_files:
            if not csv_file.exists():
                print(f"Error: File not found: {csv_file}", file=sys.stderr)
                sys.exit(1)

    # Combine CSVs into Excel
    combine_csv_to_excel(csv_files, args.output_file, create_summary=not args.no_summary)


if __name__ == "__main__":
    main()
