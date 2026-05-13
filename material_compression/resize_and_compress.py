import os
import time
from material_compression.resizelib import cleanupVTF


def resize_and_compress(folder, size, progress_callback=None):
    old_size = 0
    new_size = 0
    replace_count = 0
    start_time = time.time()
    total_files = 0
    processed = 0
    stats = {
        'resized': 0,
        'resized_and_reformatted': 0,
        'reformatted': 0,
        'format_only': 0,
        'unchanged': 0,
        'skipped_multiframe': 0,
        'errors': 0,
    }

    for path, subdirs, files in os.walk(folder):
        for name in files:
            if name.endswith('.vtf'):
                total_files += 1

    print(f'Found {total_files} VTF files to inspect.')

    for path, subdirs, files in os.walk(folder):
        for name in files:
            if not name.endswith('.vtf'):
                continue
            file_path = os.path.join(path, name)
            old_size_temp = os.path.getsize(file_path)
            try:
                result = cleanupVTF(file_path, size)
            except Exception as e:
                print(f'Error processing {file_path}: {e}')
                result = {
                    'changed': False,
                    'status': 'errors',
                    'details': str(e),
                }

            stats[result['status']] = stats.get(result['status'], 0) + 1

            if result['changed']:
                replace_count += 1
                new_size += os.path.getsize(file_path)
                old_size += old_size_temp
            else:
                new_size += old_size_temp
                old_size += old_size_temp

            processed += 1
            if processed % 100 == 0 or processed == total_files:
                changed_so_far = (
                    stats['resized']
                    + stats['resized_and_reformatted']
                    + stats['reformatted']
                    + stats['format_only']
                )
                print(
                    f'Progress: {processed}/{total_files} VTF files scanned '
                    f'({changed_so_far} changed, {stats["skipped_multiframe"]} skipped, {stats["errors"]} errors).'
                )
            if progress_callback:
                progress_callback(processed, total_files)

    print('=' * 60)
    print(f'Inspected {total_files} VTF files.')
    print('Replaced', replace_count, 'files.')
    print(
        'Change breakdown:',
        f'{stats["resized"]} resized,',
        f'{stats["resized_and_reformatted"]} resized + reformatted,',
        f'{stats["reformatted"]} reformatted,',
        f'{stats["format_only"]} format-only on multi-frame VTFs.',
    )
    print(
        'Skipped/unchanged:',
        f'{stats["skipped_multiframe"]} multi-frame,',
        f'{stats["unchanged"]} unchanged,',
        f'{stats["errors"]} errors.',
    )
    if replace_count == 0:
        print('No files were replaced.')
    else:
        print('Clamped to', size, 'resolution.')
        print('Reduced size by ', round((1 - new_size / old_size) * 100, 2), '%')
        print('Reduced size by ', round((old_size - new_size) / 1000000, 2), 'mbs')
    print('Time taken:', round(time.time() - start_time, 2), 'seconds')
    print('=' * 60)
    return (old_size - new_size, replace_count)
