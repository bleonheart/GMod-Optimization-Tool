"""
Utility module for removing empty folders from addon directories.
"""
import os
from pathlib import Path
from utils.removal_tracker import get_tracker

def remove_empty_folders(path: str, progress_callback=None) -> int:
    """Remove empty folders recursively from the specified path.

    This function walks through the directory tree and removes any folders
    that contain no files or subdirectories. It uses a bottom-up approach
    and iterates until no more empty folders are found, ensuring that parent
    folders become empty after child folders are removed are also cleaned up.

    Args:
        path: Root directory path to clean
        progress_callback: Optional callback function(current, total) for progress updates

    Returns:
        Number of empty folders removed
    """
    tracker = get_tracker()
    total_removed_count = 0
    root_path = Path(path)
    if not root_path.exists() or not root_path.is_dir():
        print(f'Warning: Path {path} does not exist or is not a directory')
        return 0
    print(f'Scanning for empty folders in: {path}')
    pass_number = 0
    max_passes = 100
    while pass_number < max_passes:
        pass_number += 1
        removed_in_pass = 0
        all_dirs = []
        for dirpath, dirnames, filenames in os.walk(path, topdown=False):
            if not dirnames and (not filenames):
                all_dirs.append(dirpath)
        total_dirs = len(all_dirs)
        if total_dirs == 0:
            break
        if pass_number == 1:
            print(f'Found {total_dirs} empty directories to remove')
        else:
            print(f'Pass {pass_number}: Found {total_dirs} additional empty directories')
        if progress_callback and pass_number == 1:
            progress_callback(0, total_dirs)
        for idx, dirpath in enumerate(all_dirs):
            try:
                if os.path.exists(dirpath) and (not os.listdir(dirpath)):
                    try:
                        rel_path = str(Path(dirpath).relative_to(root_path))
                    except ValueError:
                        rel_path = dirpath
                    os.rmdir(dirpath)
                    tracker.record_directory_removal(rel_path, 'Remove empty folders', 'Directory was empty')
                    removed_in_pass += 1
                    total_removed_count += 1
                    if (idx + 1) % 10 == 0 or idx + 1 == total_dirs:
                        if pass_number == 1:
                            print(f'Removed {idx + 1}/{total_dirs} empty folders')
                        else:
                            print(f'Pass {pass_number}: Removed {idx + 1}/{total_dirs} empty folders')
            except (OSError, FileNotFoundError) as e:
                print(f'Warning: Could not remove directory {dirpath}: {e}')
            if progress_callback and pass_number == 1:
                progress_callback(idx + 1, total_dirs)
    if pass_number >= max_passes:
        print(f'Warning: Reached maximum number of passes ({max_passes}). Some empty folders may remain.')
    if total_removed_count > 0:
        if pass_number > 1:
            print(f'✅ Removed {total_removed_count} empty folders in {pass_number} passes')
        else:
            print(f'✅ Removed {total_removed_count} empty folders')
    else:
        print('✅ No empty folders found')
    return total_removed_count
