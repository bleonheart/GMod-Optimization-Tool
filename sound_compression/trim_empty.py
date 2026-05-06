import os
import time
import warnings
import subprocess
import shutil
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', message="Couldn't find ffmpeg or avconv")
    from pydub import AudioSegment, silence

def _setup_ffmpeg():
    """Configure pydub to use ffmpeg if available"""
    common_paths = ['C:\\ffmpeg\\bin\\ffmpeg.exe', 'C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe', 'C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe', 'C:\\Users\\{}\\AppData\\Local\\Programs\\ffmpeg\\bin\\ffmpeg.exe'.format(os.environ.get('USERNAME', ''))]
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    for path in common_paths:
        if os.path.isfile(path):
            AudioSegment.ffmpeg = path
            AudioSegment.converter = path
            return True
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        AudioSegment.ffmpeg = ffmpeg_path
        AudioSegment.converter = ffmpeg_path
        return True
    print('Warning: ffmpeg not found. Audio processing may not work.')
    return False
_setup_ffmpeg()

def trim_single_audio_file(input_file, silence_thresh=-55, min_silence_len=50, fade_duration=200):
    """
    Trim silence from the end of a single audio file (WAV, MP3, or OGG) and apply fade-out.

    Args:
        input_file (str): Path to input audio file (WAV, MP3, or OGG).
        silence_thresh (int): Silence threshold in dBFS. Default -55 dB.
        min_silence_len (int): Minimum length of silence (ms) to trim. Default 50 ms.
        fade_duration (int): Duration of fade-out effect in milliseconds. Default 200 ms.
    
    Returns:
        tuple: (success, message, bytes_saved)
    """
    try:
        original_size = os.path.getsize(input_file)
        file_ext = os.path.splitext(input_file)[1].lower()
        if file_ext == '.wav':
            audio = AudioSegment.from_wav(input_file)
            export_format = 'wav'
        elif file_ext == '.mp3':
            audio = AudioSegment.from_mp3(input_file)
            export_format = 'mp3'
        elif file_ext == '.ogg':
            audio = AudioSegment.from_ogg(input_file)
            export_format = 'ogg'
        else:
            return (False, f'Unsupported file format: {file_ext}', 0)
        original_duration = len(audio)
        non_silence_ranges = silence.detect_nonsilent(audio, min_silence_len=min_silence_len, silence_thresh=silence_thresh)
        if non_silence_ranges:
            start_trim = non_silence_ranges[0][0]
            end_trim = non_silence_ranges[-1][1]
            start_silence = start_trim
            end_silence = original_duration - end_trim
            trim_start = start_silence > min_silence_len
            trim_end = end_silence > min_silence_len
            if not trim_start and (not trim_end):
                return (False, f'No significant silence to trim (start: {start_silence}ms, end: {end_silence}ms)', 0)
            trimmed_audio = audio[start_trim:end_trim]
            if len(trimmed_audio) > fade_duration:
                trimmed_audio = trimmed_audio.fade_out(fade_duration)
            else:
                trimmed_audio = trimmed_audio.fade_out(len(trimmed_audio))
            new_duration = len(trimmed_audio)
            trimmed_audio.export(input_file, format=export_format)
            new_size = os.path.getsize(input_file)
            bytes_saved = original_size - new_size
            time_saved = original_duration - new_duration
            parts = []
            if trim_start:
                parts.append(f'start ({start_silence}ms)')
            if trim_end:
                parts.append(f'end ({end_silence}ms)')
            return (True, f"Trimmed silence from {' and '.join(parts)}, saved {time_saved / 1000:.1f}s", bytes_saved)
        else:
            return (False, 'No non-silent audio detected', 0)
    except Exception as e:
        return (False, f'Error processing file: {str(e)}', 0)

def trim_empty_audio(folder, silence_thresh=-55, min_silence_len=50, fade_duration=200, progress_callback=None):
    """
    Trim silence from the end of all audio files (WAV, MP3, OGG) in the specified folder and apply fade-out.
    
    Args:
        folder (str): Path to folder containing audio files.
        silence_thresh (int): Silence threshold in dBFS. Default -55 dB.
        min_silence_len (int): Minimum length of silence (ms) to trim. Default 50 ms.
        fade_duration (int): Duration of fade-out effect in milliseconds. Default 200 ms.
        progress_callback: Optional callback function for progress updates (current, total).
    """
    old_size = 0
    new_size = 0
    processed_count = 0
    success_count = 0
    start_time = time.time()
    print(f'Scanning for audio files in: {folder}')
    print('Trimming silence from end of audio files (WAV, MP3, OGG) with fade-out...')
    audio_files = []
    if progress_callback:
        for root, dirs, files in os.walk(folder):
            for filename in files:
                file_ext = filename.lower()
                if file_ext.endswith('.wav') or file_ext.endswith('.mp3') or file_ext.endswith('.ogg'):
                    audio_files.append(os.path.join(root, filename))
        total_files = len(audio_files)
        current_file = 0
    for root, dirs, files in os.walk(folder):
        for filename in files:
            file_ext = filename.lower()
            if not (file_ext.endswith('.wav') or file_ext.endswith('.mp3') or file_ext.endswith('.ogg')):
                continue
            file_path = os.path.join(root, filename)
            if progress_callback:
                current_file += 1
                progress_callback(current_file, total_files)
            try:
                old_file_size = os.path.getsize(file_path)
                old_size += old_file_size
                success, message, bytes_saved = trim_single_audio_file(file_path, silence_thresh, min_silence_len, fade_duration)
                processed_count += 1
                if success:
                    success_count += 1
                    new_file_size = os.path.getsize(file_path)
                    new_size += new_file_size
                    saved_mb = bytes_saved / (1024 * 1024)
                    print(f'✓ {file_path} - {message} (saved {saved_mb:.2f} MB)')
                else:
                    new_size += old_file_size
            except Exception as e:
                print(f'✗ {file_path} - Error: {str(e)}')
                new_size += old_file_size
    print('=' * 60)
    print(f'Files processed: {processed_count}')
    print(f'Files modified: {success_count}')
    print(f'Files skipped: {processed_count - success_count}')
    if success_count > 0:
        total_saved = old_size - new_size
        percent_saved = total_saved / old_size * 100 if old_size > 0 else 0
        mb_saved = total_saved / (1024 * 1024)
        print(f'Total size reduction: {mb_saved:.2f} MB ({percent_saved:.1f}%)')
        print(f'Average reduction per file: {mb_saved / success_count:.2f} MB')
    else:
        print('No files were modified.')
    print(f'Time taken: {round(time.time() - start_time, 2)} seconds')
    print('=' * 60)
