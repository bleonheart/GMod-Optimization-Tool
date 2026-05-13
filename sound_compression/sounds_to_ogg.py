import os
import re
import shutil
import subprocess
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv")
    import pydub
    import pydub.exceptions

from wavinfo import WavInfoReader

_LOCAL_FFMPEG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg.exe")
_SUPPORTED_FORMATS = {"wav": "wav", "mp3": "mp3"}
_SUPPORTED_OGG_SAMPLE_RATES = {44100, 22050, 11025}
_AUDIO_STREAM_SAMPLE_RATE_RE = re.compile(r"Audio:.*?(\d+)\s*Hz", re.IGNORECASE)


def _setup_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        pydub.AudioSegment.ffmpeg = _LOCAL_FFMPEG
        pydub.AudioSegment.converter = _LOCAL_FFMPEG
        return True
    common_paths = [
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\Users\\{}\\AppData\\Local\\Programs\\ffmpeg\\bin\\ffmpeg.exe".format(os.environ.get("USERNAME", "")),
    ]
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    for path in common_paths:
        if os.path.isfile(path):
            pydub.AudioSegment.ffmpeg = path
            pydub.AudioSegment.converter = path
            return True
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        pydub.AudioSegment.ffmpeg = ffmpeg_path
        pydub.AudioSegment.converter = ffmpeg_path
        return True
    print("Warning: ffmpeg not found. Audio conversion may not work.")
    return False


_setup_ffmpeg()


def _get_ffmpeg():
    if os.path.isfile(_LOCAL_FFMPEG):
        return _LOCAL_FFMPEG
    found = shutil.which("ffmpeg")
    return found if found else "ffmpeg"


def _detect_ogg_sample_rate(filepath):
    ffmpeg = _get_ffmpeg()
    try:
        result = subprocess.run([ffmpeg, "-i", filepath], capture_output=True, text=True)
    except Exception as e:
        print(f"Failed to inspect {filepath}: {e}")
        return None
    stderr = getattr(result, "stderr", "")
    stdout = getattr(result, "stdout", "")
    output = "\n".join(part for part in (stderr, stdout) if part)
    match = _AUDIO_STREAM_SAMPLE_RATE_RE.search(output)
    if not match:
        print(f"Failed to detect sample rate for {filepath}")
        return None
    return int(match.group(1))


def _resample_ogg_file(filepath, target_rate=44100):
    ffmpeg = _get_ffmpeg()
    tmp_path = filepath + ".resample.tmp.ogg"
    cmd = [ffmpeg, "-y", "-i", filepath, "-ar", str(target_rate), "-c:a", "libvorbis", "-map_metadata", "-1", tmp_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0 and os.path.exists(tmp_path):
        os.replace(tmp_path, filepath)
        return True
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    return False


def ensure_supported_ogg_sample_rate(filepath, target_rate=44100):
    sample_rate = _detect_ogg_sample_rate(filepath)
    if sample_rate is None:
        return False
    if sample_rate in _SUPPORTED_OGG_SAMPLE_RATES:
        return False
    if _resample_ogg_file(filepath, target_rate=target_rate):
        print(f"Resampled {filepath} ({sample_rate}Hz -> {target_rate}Hz)")
        return True
    print(f"Failed to resample {filepath} ({sample_rate}Hz)")
    return False


def sounds_to_ogg(folder, progress_callback=None):
    replaced_files = {}
    old_size = 0
    new_size = 0
    replace_count = 0
    sound_files = []
    for path, _subdirs, files in os.walk(folder):
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in _SUPPORTED_FORMATS:
                sound_files.append(os.path.join(path, name))
    total = len(sound_files)
    processed = 0
    for filepath in sound_files:
        ext = filepath.rsplit(".", 1)[-1].lower()
        if progress_callback:
            processed += 1
            progress_callback(processed, total)
        if ext == "wav":
            try:
                wav_info = WavInfoReader(filepath)
            except Exception as e:
                print(f"Skipping {filepath} - could not read WAV info: {e}")
                continue
            if wav_info.cues is not None and len(wav_info.cues.cues) > 0:
                print("File", filepath, "contains cues, skipping.")
                continue
            if wav_info.smpl is not None and len(wav_info.smpl.sample_loops) > 0:
                print("File", filepath, "contains loops, skipping.")
                continue
            old_size += os.path.getsize(filepath)
            try:
                sound = pydub.AudioSegment.from_wav(filepath)
            except Exception as e:
                print(f"Skipping {filepath} - could not decode: {e}")
                old_size -= os.path.getsize(filepath)
                continue
        elif ext == "mp3":
            old_size += os.path.getsize(filepath)
            try:
                sound = pydub.AudioSegment.from_mp3(filepath)
            except pydub.exceptions.CouldntDecodeError as e:
                print(f"Skipping corrupted MP3 file: {filepath} - {e}")
                old_size -= os.path.getsize(filepath)
                continue
            except Exception as e:
                print(f"Skipping {filepath} - unexpected error: {e}")
                old_size -= os.path.getsize(filepath)
                continue
        else:
            continue
        sound = sound.set_frame_rate(44100)
        new_filepath = filepath[:filepath.rfind(".")] + ".ogg"
        sound.export(new_filepath, format="ogg")
        ffmpeg = _get_ffmpeg()
        tmp_path = new_filepath + ".tmp.ogg"
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            new_filepath,
            "-af",
            "loudnorm=I=-14.0:TP=-1.5:LRA=11",
            "-map_metadata",
            "-1",
            "-c:a",
            "libvorbis",
            "-b:a",
            "96k",
            tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, new_filepath)
        else:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            print(f"Warning: post-processing failed for {new_filepath}")
        from sound_compression.trim_empty import trim_single_audio_file

        trim_single_audio_file(new_filepath)
        ensure_supported_ogg_sample_rate(new_filepath)
        new_size += os.path.getsize(new_filepath)
        file_name = os.path.basename(filepath)
        replace_count += 1
        replaced_files[file_name] = os.path.basename(new_filepath)
        os.remove(filepath)
        print("Converted", filepath, "to ogg successfully.")
    for path, _subdirs, files in os.walk(folder):
        for name in files:
            filepath = os.path.join(path, name)
            filetype = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if filetype in ("lua", "txt", "json"):
                with open(filepath, "r", encoding="utf-8") as f:
                    contents = f.read()
                replaced = False
                for old, new in replaced_files.items():
                    pattern = re.escape(old)
                    new_contents = re.sub(pattern, new, contents, flags=re.IGNORECASE)
                    if new_contents != contents:
                        replaced = True
                    contents = new_contents
                if not replaced:
                    continue
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(contents)
                print("Updated references in", filepath)
    print("=" * 60)
    print("Converted", replace_count, "files.")
    if replace_count == 0:
        print("No files were converted.")
    elif old_size > 0:
        print("Reduced size by", round((1 - new_size / old_size) * 100, 2), "%")
        print("Reduced size by", round((old_size - new_size) / 1000000, 2), "mbs")
    print("=" * 60)
    size_saved = old_size - new_size
    return (size_saved, replace_count)


def resample_oggs(folder, target_rate=44100, progress_callback=None):
    ogg_files = []
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(".ogg"):
                ogg_files.append(os.path.join(root, name))
    total = len(ogg_files)
    old_size = 0
    new_size = 0
    count = 0
    for i, filepath in enumerate(ogg_files):
        if progress_callback:
            progress_callback(i + 1, total)
        sample_rate = _detect_ogg_sample_rate(filepath)
        if sample_rate is None:
            continue
        if sample_rate in _SUPPORTED_OGG_SAMPLE_RATES:
            continue
        old_file_size = os.path.getsize(filepath)
        print(f"Resampling {filepath} ({sample_rate}Hz -> {target_rate}Hz)")
        if _resample_ogg_file(filepath, target_rate=target_rate):
            new_file_size = os.path.getsize(filepath)
            old_size += old_file_size
            new_size += new_file_size
            count += 1
        else:
            print(f"Failed to resample {filepath}: ffmpeg returned a non-zero exit code")
    size_saved = old_size - new_size
    print(f"Resampled {count} OGG files to {target_rate}Hz.")
    return (size_saved, count)
