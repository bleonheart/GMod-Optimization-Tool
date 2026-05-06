import os
import subprocess
import shutil
_LOCAL_FFMPEG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')

def _get_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        return _LOCAL_FFMPEG
    found = shutil.which('ffmpeg')
    return found if found else 'ffmpeg'

def normalize_audio(folder, target_lufs=-14.0, progress_callback=None):
    ffmpeg = _get_ffmpeg()
    extensions = {'.ogg', '.mp3', '.wav'}
    files = []
    for root, _, filenames in os.walk(folder):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in extensions:
                files.append(os.path.join(root, name))
    total = len(files)
    count = 0
    for i, filepath in enumerate(files):
        if progress_callback:
            progress_callback(i + 1, total)
        ext = os.path.splitext(filepath)[1].lower()
        tmp_path = filepath + '.tmp' + ext
        if ext == '.ogg':
            codec = ['-c:a', 'libvorbis']
        elif ext == '.mp3':
            codec = ['-c:a', 'libmp3lame']
        else:
            codec = []
        try:
            loudnorm = f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11'
            cmd = [ffmpeg, '-y', '-i', filepath, '-af', loudnorm] + codec + [tmp_path]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0 and os.path.exists(tmp_path):
                os.replace(tmp_path, filepath)
                count += 1
                print(f'Normalized {filepath}')
            else:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                print(f'Failed to normalize {filepath}')
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f'Error processing {filepath}: {e}')
    print(f'Normalized {count} audio files to {target_lufs} LUFS.')
    return (0, count)
