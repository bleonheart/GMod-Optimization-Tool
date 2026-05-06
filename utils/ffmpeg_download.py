import io
import os
import urllib.request
import zipfile
_FFMPEG_URL = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
FFMPEG_LOCAL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ffmpeg.exe')

def ffmpeg_present() -> bool:
    return os.path.isfile(FFMPEG_LOCAL_PATH)

def download_ffmpeg(progress_callback=None) -> bool:
    """Download the latest ffmpeg.exe into the app root directory.

    progress_callback(downloaded_bytes, total_bytes) is called periodically.
    Returns True on success, False on failure.
    """
    try:
        print('Downloading ffmpeg (this only happens once)...')
        request = urllib.request.Request(_FFMPEG_URL, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(request, timeout=60)
        total = int(response.headers.get('Content-Length', 0))
        buf = io.BytesIO()
        downloaded = 0
        chunk_size = 65536
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            buf.write(chunk)
            downloaded += len(chunk)
            if progress_callback and total > 0:
                progress_callback(downloaded, total)
        print('Extracting ffmpeg.exe...')
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            for name in z.namelist():
                if name.endswith('/bin/ffmpeg.exe') or name == 'bin/ffmpeg.exe':
                    with z.open(name) as src, open(FFMPEG_LOCAL_PATH, 'wb') as dst:
                        dst.write(src.read())
                    print(f'ffmpeg.exe saved to: {FFMPEG_LOCAL_PATH}')
                    return True
        print('Error: ffmpeg.exe not found inside the downloaded archive.')
        return False
    except Exception as e:
        print(f'Error downloading ffmpeg: {e}')
        return False
