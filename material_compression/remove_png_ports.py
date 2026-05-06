import os

def remove_png_ports(folder, progress_callback=None):
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if not name.lower().endswith('.png'):
                continue
            png_path = os.path.join(root, name)
            dds_path = os.path.splitext(png_path)[0] + '.dds'
            if os.path.exists(dds_path):
                files.append((png_path, dds_path))
    total = len(files)
    removed_size = 0
    removed_count = 0
    for i, (png_path, dds_path) in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total)
        try:
            removed_size += os.path.getsize(png_path)
            os.remove(png_path)
            removed_count += 1
            print(f'Removed PNG port: {png_path} (DDS exists: {dds_path})')
        except Exception as e:
            print(f'Failed to remove {png_path}: {e}')
    print(f'Removed {removed_count} PNG ports.')
    return (removed_size, removed_count)
