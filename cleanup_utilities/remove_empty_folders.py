"""
Command-line utility to remove empty folders from a directory.
Usage: python -m cleanup_utilities.remove_empty_folders <path_to_directory>
"""
import os
import sys
from utils.remove_empty_folders import remove_empty_folders

def main():
    if len(sys.argv) != 2:
        print('Usage: python -m cleanup_utilities.remove_empty_folders <path_to_directory>')
        print('Example: python -m cleanup_utilities.remove_empty_folders C:\\my\\addon\\content')
        sys.exit(1)
    target_path = sys.argv[1]
    if not os.path.exists(target_path):
        print(f"Error: Path '{target_path}' does not exist")
        sys.exit(1)
    if not os.path.isdir(target_path):
        print(f"Error: Path '{target_path}' is not a directory")
        sys.exit(1)
    print(f'Removing empty folders from: {target_path}')
    print('=' * 50)
    try:
        removed_count = remove_empty_folders(target_path)
        print('=' * 50)
        print(f'Successfully removed {removed_count} empty folders')
    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)
if __name__ == '__main__':
    main()
