import os
from PIL import Image
_CONVERTIBLE = {'.jpg', '.jpeg', '.bmp', '.tga', '.gif', '.tiff', '.webp'}

def convert_images_to_png(folder, progress_callback=None):
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in _CONVERTIBLE:
                files.append(os.path.join(root, name))
    total = len(files)
    old_size = 0
    new_size = 0
    count = 0
    for i, filepath in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total)
        try:
            old_size += os.path.getsize(filepath)
            img = Image.open(filepath).convert('RGBA')
            png_path = os.path.splitext(filepath)[0] + '.png'
            img.save(png_path, 'PNG')
            new_size += os.path.getsize(png_path)
            os.remove(filepath)
            count += 1
            print(f'Converted {filepath} to PNG')
        except Exception as e:
            print(f'Failed to convert {filepath}: {e}')
    size_saved = old_size - new_size
    print(f'Converted {count} images to PNG.')
    return (size_saved, count)
