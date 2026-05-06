import os
import subprocess
import shutil
from sound_compression.trim_empty import trim_single_audio_file
_LOCAL_FFMPEG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')

def _get_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        return _LOCAL_FFMPEG
    found = shutil.which('ffmpeg')
    return found if found else 'ffmpeg'

def reencode_oggs(folder, bitrate_kbps=96, progress_callback=None):
    ffmpeg = _get_ffmpeg()
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if name.lower().endswith('.ogg'):
                files.append(os.path.join(root, name))
    total = len(files)
    old_size = 0
    new_size = 0
    count = 0
    for i, filepath in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total)
        tmp_path = filepath + '.tmp.ogg'
        old_file_size = os.path.getsize(filepath)
        try:
            cmd = [ffmpeg, '-y', '-i', filepath, '-af', 'loudnorm=I=-14.0:TP=-1.5:LRA=11', '-map_metadata', '-1', '-c:a', 'libvorbis', '-b:a', f'{bitrate_kbps}k', tmp_path]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0 and os.path.exists(tmp_path):
                os.replace(tmp_path, filepath)
                trim_single_audio_file(filepath)
                new_file_size = os.path.getsize(filepath)
                old_size += old_file_size
                new_size += new_file_size
                count += 1
                saved = old_file_size - new_file_size
                print(f'Re-encoded {filepath} at {bitrate_kbps}kbps (saved {saved} bytes)')
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                print(f'Failed to re-encode {filepath}')
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f'Error processing {filepath}: {e}')
    size_saved = old_size - new_size
    print(f'Re-encoded {count} OGG files at {bitrate_kbps}kbps.')
    return (size_saved, count)
