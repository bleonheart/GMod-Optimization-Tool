import os
from utils.removal_tracker import get_tracker

def unused_model_formats(folder, remove=True, progress_callback=None):
    total_size = 0
    count = 0
    formats_to_remove = ['.dx80.vtx', '.xbox.vtx', '.sw.vtx', '.360.vtx']
    files_to_process = []
    if progress_callback:
        for root, _, files in os.walk(folder):
            for file in files:
                for fmt in formats_to_remove:
                    if file.endswith(fmt):
                        files_to_process.append((root, file))
        total_count = len(files_to_process)
        processed = 0
    tracker = get_tracker()
    for root, _, files in os.walk(folder):
        for file in files:
            for fmt in formats_to_remove:
                if file.endswith(fmt):
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    if remove:
                        os.remove(file_path)
                        rel_path = os.path.relpath(file_path, folder).replace('\\', '/')
                        tracker.record_file_removal(rel_path, 'Unused model formats', file_size, f'Unused model format file ({fmt})')
                        print('Removed', file_path)
                    else:
                        print('Found unused file:', file_path)
                    count += 1
                    if progress_callback:
                        processed += 1
                        progress_callback(processed, total_count)
    return (total_size, count)
