import os
import shutil
import subprocess
from PIL import Image
_LOCAL_FFMPEG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')

def _get_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        return _LOCAL_FFMPEG
    found = shutil.which('ffmpeg')
    return found if found else 'ffmpeg'

def _should_whiten_transparent_texture(source_path):
    normalized = os.path.normpath(source_path).lower()
    return f'{os.sep}textures{os.sep}interface{os.sep}icons{os.sep}' in normalized

def _normalize_transparent_texture(png_path, source_path):
    if not _should_whiten_transparent_texture(source_path):
        return
    with Image.open(png_path).convert('RGBA') as img:
        alpha = img.getchannel('A')
        histogram = alpha.histogram()
        transparent_pixels = histogram[0]
        total_pixels = img.width * img.height
        transparent_ratio = transparent_pixels / total_pixels if total_pixels else 0
        if transparent_ratio < 0.05:
            return
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.putalpha(alpha)
        white.save(png_path, 'PNG')

def convert_dds_to_png(folder, delete_originals=True, progress_callback=None):
    ffmpeg = _get_ffmpeg()
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if name.lower().endswith('.dds'):
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
            png_path = os.path.splitext(filepath)[0] + '.png'
            result = subprocess.run([ffmpeg, '-y', '-i', filepath, '-vf', 'format=rgba', '-pix_fmt', 'rgba', png_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode != 0:
                print(f'Failed to convert {filepath}: ffmpeg returned {result.returncode}')
                continue
            _normalize_transparent_texture(png_path, filepath)
            new_size += os.path.getsize(png_path)
            if delete_originals:
                os.remove(filepath)
            count += 1
            print(f'Converted: {filepath}')
        except Exception as e:
            print(f'Failed to convert {filepath}: {e}')
    size_diff = old_size - new_size
    print(f'Converted {count} DDS files to PNG.')
    return (size_diff, count)
