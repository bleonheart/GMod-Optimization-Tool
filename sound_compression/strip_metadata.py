import os
import subprocess
import shutil
_LOCAL_FFMPEG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')

def _get_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        return _LOCAL_FFMPEG
    found = shutil.which('ffmpeg')
    return found if found else 'ffmpeg'

def strip_audio_metadata(folder, progress_callback=None):
    ffmpeg = _get_ffmpeg()
    extensions = {'.ogg', '.mp3'}
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in extensions:
                files.append(os.path.join(root, name))
    total = len(files)
    old_size = 0
    new_size = 0
    count = 0
    for i, filepath in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total)
        ext = os.path.splitext(filepath)[1].lower()
        tmp_path = filepath + '.tmp' + ext
        old_file_size = os.path.getsize(filepath)
        try:
            cmd = [ffmpeg, '-y', '-i', filepath, '-map_metadata', '-1', '-c:a', 'copy', tmp_path]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0 and os.path.exists(tmp_path):
                new_file_size = os.path.getsize(tmp_path)
                old_size += old_file_size
                new_size += new_file_size
                os.replace(tmp_path, filepath)
                count += 1
                saved = old_file_size - new_file_size
                print(f'Stripped metadata: {filepath} (saved {saved} bytes)')
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                print(f'Failed to strip metadata: {filepath}')
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f'Error processing {filepath}: {e}')
    size_saved = old_size - new_size
    print(f'Stripped metadata from {count} audio files.')
    return (size_saved, count)
