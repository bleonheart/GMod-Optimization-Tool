import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from io import StringIO
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
SETTINGS_FILE = os.path.join(PROJECT_ROOT, 'settings.json')
DEFAULT_GMOD_DIR = 'D:\\SteamLibrary\\steamapps\\common\\GarrysMod'
ADDON_CONTENT_DIR_NAMES = {'autorun', 'cfg', 'data', 'effects', 'entities', 'gamemodes', 'lua', 'maps', 'materials', 'models', 'particles', 'resource', 'scenes', 'scripts', 'sound', 'sounds', 'weapons'}
ADDON_CONTENT_FILE_NAMES = {'addon.json', 'addon.txt'}
from PySide6 import QtCore, QtGui, QtWidgets
from utils.ffmpeg_download import ffmpeg_present, download_ffmpeg
from utils.formatting import format_size
from utils.removal_tracker import get_tracker, reset_tracker
from unused_files.modelformats import unused_model_formats
from unused_files.content import unused_content
from unused_files.remove_game_files import remove_game_files
from material_compression.resize_and_compress import resize_and_compress
from material_compression.resize_png import clamp_pngs
from material_compression.remove_mipmaps import remove_mipmaps
from sound_compression.sounds_to_ogg import sounds_to_ogg, resample_oggs
from sound_compression.trim_empty import trim_empty_audio
from sound_compression.strip_metadata import strip_audio_metadata
from sound_compression.normalize_audio import normalize_audio
from sound_compression.reencode_ogg import reencode_oggs
from material_compression.convert_to_png import convert_images_to_png
from material_compression.convert_dds_to_png import convert_dds_to_png
from material_compression.remove_png_ports import remove_png_ports
from mapping.find_map_content import find_map_content
from utils.addon_merge_clean_split import merge_addon_workflow, extract_missing_materials_to_markdown, extract_content_packs, recover_missing_materials_from_content_packs, remove_models_with_missing_materials
from utils.remove_comments import remove_comments_from_directory
from utils.remove_empty_folders import remove_empty_folders

FULL_IMAGE_WORKFLOW_STEPS = [
    ('dds_to_png', 'Convert DDS files to PNG'),
    ('images_to_png', 'Convert images to PNG'),
    ('vtf_to_dxt', 'Convert VTFs to DXT'),
    ('clamp_vtf', 'Clamp VTF file sizes to 1024px'),
    ('remove_mipmaps', 'Remove mipmaps'),
    ('resave_vtf', 'Resave VTF files (autorefresh)'),
    ('clamp_png', 'Clamp PNG files to 512px'),
]
FULL_SOUND_WORKFLOW_STEPS = [
    ('sounds_to_ogg', 'Convert sound files to OGG'),
    ('resample_oggs', 'Resample unsupported OGG sample rates'),
    ('strip_audio_metadata', 'Strip audio metadata'),
]
FULL_WORKFLOW_STEPS = [
    ('unused_model_formats', 'Remove unused model formats'),
    ('remove_game_files', "Remove files already provided by Garry's Mod"),
    ('remove_empty_folders', 'Remove empty folders'),
    ('remove_comments', 'Remove comments from Lua files'),
    *FULL_IMAGE_WORKFLOW_STEPS,
    *FULL_SOUND_WORKFLOW_STEPS,
    ('missing_materials_report', 'Generate a missing materials report'),
]

class SignalStream(QtCore.QObject):
    text_emitted = QtCore.Signal(str)

    def write(self, text: str):
        if text:
            self.text_emitted.emit(str(text))

    def flush(self):
        pass

@contextmanager
def redirect_stdout_stderr(callback):
    """Temporarily redirect stdout/stderr to a Qt signal callback."""
    old_out, old_err = (sys.stdout, sys.stderr)
    stream = SignalStream()
    stream.text_emitted.connect(callback)
    sys.stdout = stream
    sys.stderr = stream
    try:
        yield
    finally:
        sys.stdout = old_out
        sys.stderr = old_err

class TaskWorker(QtCore.QObject):
    started = QtCore.Signal(str)
    log = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)
    finished = QtCore.Signal(str, str)
    failed = QtCore.Signal(str, str)

    def __init__(self, fn, *args, description: str='Working...', modified_folder=None, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.description = description
        self.modified_folder = modified_folder

    @QtCore.Slot()
    def run(self):
        self.started.emit(self.description)
        try:
            with redirect_stdout_stderr(self.log.emit):
                result = self.fn(*self.args, **self.kwargs)
            msg = 'Done.'
            if isinstance(result, tuple):
                try:
                    size, count = result
                    msg = f'Done. Files: {count}, Size: {format_size(size)}'
                except Exception:
                    pass
            self.finished.emit(msg, self.modified_folder or '')
        except Exception as e:
            self.failed.emit(f'Error: {e}', self.modified_folder or '')


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('GM Addon Optimization Tools')
        self.resize(980, 720)
        icon_path = os.path.join(PROJECT_ROOT, 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))
        self.thread: QtCore.QThread | None = None
        self.worker: TaskWorker | None = None
        self.initial_folder_size: int = 0
        self.current_folder_size: int = 0
        self.last_content_folder: str = ''
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        folders_group = QtWidgets.QGroupBox('Work Folders')
        folders_form = QtWidgets.QFormLayout()
        folders_form.setHorizontalSpacing(8)
        folders_form.setVerticalSpacing(6)

        def make_folder_row(placeholder: str, browse_title: str):
            row = QtWidgets.QHBoxLayout()
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText(placeholder)
            btn = QtWidgets.QPushButton('Browse…')
            btn.setFixedWidth(80)
            row.addWidget(edit)
            row.addWidget(btn)

            def browse():
                path = QtWidgets.QFileDialog.getExistingDirectory(self, browse_title, edit.text() or '')
                if path:
                    edit.setText(path)
                    self._save_settings()
            btn.clicked.connect(browse)
            edit.editingFinished.connect(self._save_settings)
            return (row, edit)
        content_row, self.content_folder_edit = make_folder_row('Content folder path…', 'Select content folder')
        gmod_row, self.gmod_folder_edit = make_folder_row('GMod folder path…', "Select Garry's Mod folder")
        addon_source_row, self.addon_source_edit = make_folder_row('Folder containing addon subfolders to merge…', 'Select addon source folder')
        addon_output_row, self.addon_output_edit = make_folder_row('Merged output / pack root folder…', 'Select addon output folder')
        packs_row, self.content_packs_edit = make_folder_row('Folder containing content-pack subfolders…', 'Select content packs folder')
        folders_form.addRow('Content Folder:', content_row)
        folders_form.addRow('GMod Folder:', gmod_row)
        folders_form.addRow('Addon Source:', addon_source_row)
        folders_form.addRow('Addon Output:', addon_output_row)
        folders_form.addRow('Content Packs:', packs_row)
        folders_group.setLayout(folders_form)
        main_layout.addWidget(folders_group)
        self._load_settings()
        self.content_folder_edit.editingFinished.connect(self._on_content_folder_changed)
        self.addon_source_edit.editingFinished.connect(self._save_settings)
        self.addon_output_edit.editingFinished.connect(self._save_settings)
        self.content_packs_edit.editingFinished.connect(self._save_settings)
        size_row = QtWidgets.QHBoxLayout()
        self.size_label = QtWidgets.QLabel('Folder size: Not calculated yet')
        self.size_label.setStyleSheet('QLabel { padding: 5px; }')
        size_row.addWidget(self.size_label)
        size_row.addStretch()
        main_layout.addLayout(size_row)
        legend_label = QtWidgets.QLabel("💡 <span style='color: #4CAF50;'>Green buttons</span> generally have no downsides and can always be used.")
        legend_label.setTextFormat(QtCore.Qt.RichText)
        main_layout.addWidget(legend_label)
        tip_label = QtWidgets.QLabel('💡 Hover over buttons to see more information about what they do.')
        main_layout.addWidget(tip_label)
        actions_container = QtWidgets.QWidget()
        actions_layout = QtWidgets.QVBoxLayout(actions_container)
        actions_layout.setSpacing(12)

        def add_button(grid, row, text, handler, recommended=False, tooltip=None):
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(handler)
            if recommended:
                btn.setStyleSheet('QPushButton { color: #4CAF50; font-weight: bold; }')
            if tooltip:
                btn.setToolTip(tooltip)
            grid.addWidget(btn, row // 2, row % 2)
            return btn
        textures_group = QtWidgets.QGroupBox('Textures Compression')
        textures_grid = QtWidgets.QGridLayout()
        textures_grid.setHorizontalSpacing(12)
        textures_grid.setVerticalSpacing(8)
        add_button(textures_grid, 0, 'Clamp VTF file sizes', self.on_clamp_vtf, tooltip='Resize VTF textures to a maximum size.\nHelps reduce file size without losing quality for most textures.\n512 is good for most usecases like player models, 1024/2048 for world textures.')
        add_button(textures_grid, 1, 'Use DXT for VTFs', self.on_use_dxt, recommended=True, tooltip='Convert VTF textures to DXT compression format. Reduces file size significantly with minimal quality loss.')
        add_button(textures_grid, 2, 'Remove mipmaps', self.on_remove_mipmaps, tooltip='Remove mipmaps from textures.\nUseful for closeup textures like viewmodel textures but may cause ugly texture shimmering on large textures viewed from a distance.')
        add_button(textures_grid, 3, 'Clamp PNG file sizes', self.on_clamp_png, recommended=True, tooltip="Resize PNG images to a maximum size.\nReduces file size for UI elements and other PNG assets.\nUsually PNG's don't need to be very large as they are often used for icons or UI elements.")
        add_button(textures_grid, 4, 'Resave VTF files (autorefresh)', self.on_resave_vtf, tooltip='Resave all VTF files to force the game to refresh cached textures.')
        add_button(textures_grid, 5, 'Convert images to PNG', self.on_convert_to_png, tooltip='Convert JPG, BMP, TGA, GIF, TIFF, and WebP images to PNG using Pillow.\nUseful for ensuring consistent image formats across the addon.')
        add_button(textures_grid, 6, 'Convert DDS to PNG', self.on_convert_dds_to_png, tooltip='Convert all DDS textures in the content folder to PNG using ffmpeg.\nUseful for interface textures that need to be in PNG format.')
        add_button(textures_grid, 7, 'Remove PNG Ports', self.on_remove_png_ports, tooltip='Remove PNG files that appear to be DDS ports by deleting any `.png` file that has a same-name `.dds` beside it.')
        textures_group.setLayout(textures_grid)
        actions_layout.addWidget(textures_group)
        cleanup_group = QtWidgets.QGroupBox('Cleanup Utilities')
        cleanup_grid = QtWidgets.QGridLayout()
        cleanup_grid.setHorizontalSpacing(12)
        cleanup_grid.setVerticalSpacing(8)
        add_button(cleanup_grid, 0, 'Scan unused model formats', self.on_scan_unused_model_formats, recommended=True, tooltip="Scan for unused model format files (.dx80.vtx, .xbox.vtx, .sw.vtx, .360.vtx) that are not used by Garry's Mod.")
        add_button(cleanup_grid, 1, 'Remove unused model formats', self.on_remove_unused_model_formats, recommended=True, tooltip="Remove unused model format files (.dx80.vtx, .xbox.vtx, .sw.vtx, .360.vtx) that are not used by Garry's Mod.")
        add_button(cleanup_grid, 2, 'Remove files already in game (HL2/CSS)', self.on_remove_game_files, recommended=True, tooltip='Remove files that are already provided by base GMod.\nCan reduce size significantly for addons that include EP1/EP2/CSS content.')
        add_button(cleanup_grid, 3, 'Remove empty folders', self.on_remove_empty_folders, recommended=True, tooltip='Remove all empty directories from the content folder.\nThis cleans up folder structure after file removal operations.')
        add_button(cleanup_grid, 4, 'Find and copy content used by .bsp', self.on_find_map_content, tooltip='Extract all content referenced by a BSP map file and copy it to a new folder for easy map packing.')
        add_button(cleanup_grid, 5, 'Find unused material textures', self.on_find_unused_materials, recommended=True, tooltip='Scan model material directories for `.vtf` texture files not referenced by Lua-used models.\nIgnores `.png`, `.jpg`, and other image-style files.')
        add_button(cleanup_grid, 6, 'Remove unused material textures', self.on_remove_unused_materials, recommended=True, tooltip='Remove unused `.vtf` texture files from model material directories when they are not referenced by Lua-used models.\nIgnores `.png`, `.jpg`, and other image-style files.')
        add_button(cleanup_grid, 7, 'Find missing materials', self.on_find_missing_materials, recommended=True, tooltip="Scan model material directories and report ones that are missing from the addon and optional Garry's Mod fallback.")
        add_button(cleanup_grid, 8, 'Recover Missing Materials From Content Packs', self.on_recover_missing_materials, tooltip='Scan for missing model materials, search a content-pack root for matching files, and copy the found .vmt/.vtf assets into the content folder.')
        add_button(cleanup_grid, 9, 'Find models with missing textures', self.on_find_models_with_missing_textures, tooltip='Scan and list all models whose material directories or VMT texture files are missing, without deleting anything.')
        add_button(cleanup_grid, 10, 'Remove comments from Lua files', self.on_remove_comments, recommended=True, tooltip='Remove single-line and inline comments from Lua files while preserving long comment blocks.\nAlso runs glualint pretty-print for code formatting.\nReduces file size and improves code clarity.')
        cleanup_group.setLayout(cleanup_grid)
        actions_layout.addWidget(cleanup_group)
        audio_group = QtWidgets.QGroupBox('Audio Compression')
        audio_grid = QtWidgets.QGridLayout()
        audio_grid.setHorizontalSpacing(12)
        audio_grid.setVerticalSpacing(8)
        add_button(audio_grid, 0, 'Convert sound to OGG', self.on_sounds_to_ogg, recommended=True, tooltip='Convert all WAV and MP3 sound files in the content folder to OGG at 44.1 kHz.\nSkips WAV files with loop or cue points.')
        add_button(audio_grid, 1, 'Trim silence', self.on_trim_empty_audio, tooltip='Remove silent audio from the start and end of sound files.\nApplies a fade-out at the tail to prevent hard cuts.')
        add_button(audio_grid, 2, 'Re-encode existing OGGs', self.on_reencode_oggs, tooltip='Re-encode all OGG files in the content folder at a specified bitrate (64–128 kbps).\nCan significantly reduce size of OGG files that were encoded at a high bitrate.')
        add_button(audio_grid, 3, 'Resample', self.on_resample_oggs, tooltip='Resample any OGG files not already at 44100Hz to 44.1kHz.\nUseful for OGGs that came in at 22.05kHz, 11.025kHz, or 48kHz.')
        add_button(audio_grid, 4, 'Normalize the volume', self.on_normalize_audio, tooltip="Normalize loudness of all audio files to -14 LUFS using ffmpeg's loudnorm filter.\nHelps with inconsistently loud or quiet sounds.")
        add_button(audio_grid, 5, 'Strip metadata from audio', self.on_strip_audio_metadata, recommended=True, tooltip='Remove embedded album art, tags, and other metadata from OGG and MP3 files.\nReduces file size without affecting audio quality.')
        add_button(audio_grid, 6, 'Run Full Sound Workflow', self.on_run_full_sound_workflow, recommended=True, tooltip='Run the full sound cleanup workflow on the current content folder.\nIncludes OGG conversion, OGG resampling, and metadata stripping.')
        audio_group.setLayout(audio_grid)
        actions_layout.addWidget(audio_group)
        merge_group = QtWidgets.QGroupBox('File Merging')
        merge_grid = QtWidgets.QGridLayout()
        merge_grid.setHorizontalSpacing(12)
        merge_grid.setVerticalSpacing(8)
        add_button(merge_grid, 0, 'Run Addon Merge / Split Workflow', self.on_run_addon_merge_workflow, tooltip='Merge top-level addon folders into the output folder, then optionally split the merged result into numbered content packs using the options above.')
        add_button(merge_grid, 1, 'Import Content Packs Into Content Folder', self.on_extract_content_packs, tooltip='Go through a folder of content packs, detect the real content root in each pack, and copy the files into the current content folder in the correct layout.')
        add_button(merge_grid, 2, 'Run Full Workflow (Except Merge)', self.on_run_full_workflow, recommended=True, tooltip='Run the main cleanup workflow on the current content folder without importing or merging content packs first.\nRequires the Content Folder and GMod Folder fields to be filled in first.')
        add_button(merge_grid, 3, 'Run Full Image Workflow', self.on_run_full_image_workflow, recommended=True, tooltip='Run the full image and texture workflow on the current content folder.\nIncludes DDS/image conversion, VTF optimization, and PNG clamping.')
        merge_group.setLayout(merge_grid)
        actions_layout.addWidget(merge_group)
        backup_group = QtWidgets.QGroupBox('Backup')
        backup_grid = QtWidgets.QGridLayout()
        backup_grid.setHorizontalSpacing(12)
        backup_grid.setVerticalSpacing(8)
        add_button(backup_grid, 0, 'Back Up Content Folder', self.on_backup_content_folder, tooltip="Create a timestamped backup copy of the current content folder inside the app's backups folder.")
        add_button(backup_grid, 1, 'Load Content Folder Backup', self.on_restore_content_folder_backup, tooltip='Replace the current content folder with files from one of the saved content-folder backups.')
        add_button(backup_grid, 2, 'Back Up Content Packs', self.on_backup_content_packs, tooltip="Create a timestamped backup copy of the current content-packs folder inside the app's backups folder.")
        add_button(backup_grid, 3, 'Load Content Packs Backup', self.on_restore_content_packs_backup, tooltip='Replace the current content-packs folder with files from one of the saved content-pack backups.')
        self.content_folder_backup_label = QtWidgets.QLabel()
        self.content_packs_backup_label = QtWidgets.QLabel()
        backup_grid.addWidget(self.content_folder_backup_label, 2, 0, 1, 2)
        backup_grid.addWidget(self.content_packs_backup_label, 3, 0, 1, 2)
        backup_group.setLayout(backup_grid)
        benchmark_group = QtWidgets.QGroupBox('Benchmark')
        benchmark_grid = QtWidgets.QGridLayout()
        benchmark_grid.setHorizontalSpacing(12)
        benchmark_grid.setVerticalSpacing(8)
        add_button(benchmark_grid, 0, 'Benchmark Textures', self.on_benchmark_full_image_workflow, tooltip='Clone the current content folder, run the texture and image workflow on the clone, report size savings, then delete the clone.')
        add_button(benchmark_grid, 1, 'Benchmark Cleanup', self.on_benchmark_cleanup_workflow, tooltip='Clone the current content folder, run the cleanup workflow on the clone, report size savings, then delete the clone.')
        add_button(benchmark_grid, 2, 'Benchmark Audio', self.on_benchmark_full_sound_workflow, tooltip='Clone the current content folder, run the sound workflow on the clone, report size savings, then delete the clone.')
        add_button(benchmark_grid, 3, 'Benchmark Full Workflow', self.on_benchmark_full_workflow, tooltip='Clone the current content folder, run the full workflow on the clone, report size savings, then delete the clone.')
        benchmark_group.setLayout(benchmark_grid)
        actions_layout.addWidget(benchmark_group)
        actions_layout.addWidget(backup_group)
        actions_layout.addStretch()
        actions_scroll = QtWidgets.QScrollArea()
        actions_scroll.setWidgetResizable(True)
        actions_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        actions_scroll.setWidget(actions_container)
        main_layout.addWidget(actions_scroll, 1)
        progress_row = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        progress_row.addWidget(self.progress)
        main_layout.addLayout(progress_row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('Status and output will appear here…')
        self.log.setMaximumHeight(140)
        main_layout.addWidget(self.log)
        QtWidgets.QApplication.setStyle('Fusion')
        self.apply_dark_palette()
        self.refresh_backup_status_labels()

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
        self.content_folder_edit.setText(data.get('content_folder', ''))
        self.gmod_folder_edit.setText(data.get('gmod_folder', DEFAULT_GMOD_DIR))
        self.addon_source_edit.setText(data.get('addon_source', ''))
        self.addon_output_edit.setText(data.get('addon_output', ''))
        self.content_packs_edit.setText(data.get('content_packs', ''))

    def _save_settings(self):
        data = {'content_folder': self.content_folder_edit.text().strip(), 'gmod_folder': self.gmod_folder_edit.text().strip(), 'addon_source': self.addon_source_edit.text().strip(), 'addon_output': self.addon_output_edit.text().strip(), 'content_packs': self.content_packs_edit.text().strip()}
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f'Warning: Could not save settings: {e}')

    def _on_content_folder_changed(self):
        self._save_settings()
        path = self.content_folder_edit.text().strip()
        if path and os.path.isdir(path):
            self.remember_content_folder(path)

    def apply_dark_palette(self):
        palette = QtGui.QPalette()
        base = QtGui.QColor(45, 45, 45)
        alt = QtGui.QColor(53, 53, 53)
        text = QtGui.QColor(220, 220, 220)
        highlight = QtGui.QColor(42, 130, 218)
        palette.setColor(QtGui.QPalette.Window, alt)
        palette.setColor(QtGui.QPalette.WindowText, text)
        palette.setColor(QtGui.QPalette.Base, base)
        palette.setColor(QtGui.QPalette.AlternateBase, alt)
        palette.setColor(QtGui.QPalette.ToolTipBase, text)
        palette.setColor(QtGui.QPalette.ToolTipText, text)
        palette.setColor(QtGui.QPalette.Text, text)
        palette.setColor(QtGui.QPalette.Button, alt)
        palette.setColor(QtGui.QPalette.ButtonText, text)
        palette.setColor(QtGui.QPalette.BrightText, QtCore.Qt.red)
        palette.setColor(QtGui.QPalette.Highlight, highlight)
        palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.black)
        self.setPalette(palette)

    def current_content_folder(self) -> str:
        return (self.last_content_folder or '').strip().strip('"')

    def remember_content_folder(self, folder: str):
        folder = (folder or '').strip().strip('"')
        if not folder:
            return
        self.last_content_folder = folder
        if os.path.exists(folder) and os.path.isdir(folder):
            self.calculate_initial_folder_size(folder)
        else:
            self.initial_folder_size = 0
            self.current_folder_size = 0
            self.update_size_label()

    def ensure_content_folder(self, title: str='Select content folder') -> str | None:
        preset = self.content_folder_edit.text().strip()
        if preset and os.path.isdir(preset):
            self.remember_content_folder(preset)
            return preset
        folder = self.ask_directory(title)
        if not folder or not os.path.exists(folder):
            QtWidgets.QMessageBox.warning(self, 'Folder missing', 'Please choose a valid content folder.')
            return None
        self.remember_content_folder(folder)
        return folder

    def is_addon_content_folder(self, folder: str) -> bool:
        if not folder or not os.path.isdir(folder):
            return False
        try:
            entries = os.listdir(folder)
        except OSError:
            return False
        lowered = {name.lower() for name in entries}
        if any((name in lowered and os.path.isdir(os.path.join(folder, name)) for name in ADDON_CONTENT_DIR_NAMES)):
            return True
        if any((name in lowered and os.path.isfile(os.path.join(folder, name)) for name in ADDON_CONTENT_FILE_NAMES)):
            return True
        return False

    def resolve_content_targets(self, folder: str) -> tuple[list[tuple[str, str]], bool]:
        folder = os.path.abspath(os.path.normpath(folder))
        child_dirs = []
        try:
            for entry in sorted(os.scandir(folder), key=lambda item: item.name.lower()):
                if entry.is_dir():
                    child_dirs.append((entry.name, entry.path))
        except OSError:
            child_dirs = []
        addon_dirs = [(name, path) for name, path in child_dirs if self.is_addon_content_folder(path)]
        if self.is_addon_content_folder(folder) or not addon_dirs:
            return ([(os.path.basename(folder) or 'content', folder)], False)
        return (addon_dirs, True)

    def sanitize_output_name(self, name: str) -> str:
        cleaned = ''.join((ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in (name or '').strip()))
        cleaned = cleaned.strip('._')
        return cleaned or 'addon'

    def build_addon_output_file(self, output_path: str, addon_name: str, is_multi: bool) -> str:
        if not is_multi:
            return output_path
        root, ext = os.path.splitext(output_path)
        return f'{root}_{self.sanitize_output_name(addon_name)}{ext}'

    def build_addon_output_folder(self, output_folder: str, addon_name: str, is_multi: bool) -> str:
        if not is_multi:
            return output_folder
        return os.path.join(output_folder, self.sanitize_output_name(addon_name))

    def run_content_targets(self, selected_folder: str, workflow_name: str, addon_runner, result_mapper=None):
        targets, is_multi = self.resolve_content_targets(selected_folder)
        print(f'Selected content path: {selected_folder}')
        if is_multi:
            print(f'Detected addon container with {len(targets)} addon folders.')
        else:
            print(f'Detected single addon folder: {targets[0][0]}')
        if result_mapper is None:
            result_mapper = lambda result: result if isinstance(result, tuple) and len(result) >= 2 else None
        total_size = 0
        total_count = 0
        mapped_results = 0
        for index, (addon_name, addon_path) in enumerate(targets, start=1):
            print('')
            print('=' * 80)
            print(f'{workflow_name.upper()} [{index}/{len(targets)}]: {addon_name}')
            print('=' * 80)
            print(f'Addon folder: {addon_path}')
            result = addon_runner(addon_path, addon_name, index, len(targets), is_multi)
            mapped = result_mapper(result)
            if mapped is None:
                continue
            total_size += mapped[0]
            total_count += mapped[1]
            mapped_results += 1
        if len(targets) > 1:
            print('')
            print('=' * 80)
            print(f'{workflow_name.upper()} SUMMARY')
            print('=' * 80)
            print(f'Processed addon folders: {len(targets)}')
            if mapped_results:
                print(f'Total files/items: {total_count}')
                print(f'Total size: {format_size(total_size)}')
        if mapped_results:
            return (total_size, total_count)
        return (0, len(targets))

    def current_gmod_folder(self) -> str | None:
        path = self.gmod_folder_edit.text().strip()
        if path and os.path.isdir(path):
            return path
        return None

    def ask_optional_lua_folder(self) -> str | None:
        if not self.ask_yes_no('Lua folder', 'Do you want to select a Lua folder for reference scanning?'):
            return None
        folder = self.ask_directory('Select lua folder')
        if not folder:
            return None
        if not os.path.exists(folder):
            QtWidgets.QMessageBox.warning(self, 'Invalid lua folder', "The selected Lua folder doesn't exist.")
            return None
        return folder

    def ask_optional_gmod_dir(self, prompt_text: str) -> str | None:
        preset = self.current_gmod_folder()
        if preset:
            return preset
        if not self.ask_yes_no("Garry's Mod Directory", prompt_text):
            return None
        gmod_dir = self.ask_directory("Select Garry's Mod directory (garrysmod folder)")
        if gmod_dir and (not os.path.exists(os.path.join(gmod_dir, 'addons'))):
            QtWidgets.QMessageBox.warning(self, 'Invalid directory', "The selected directory doesn't appear to be a valid Garry's Mod directory.\nContinuing without it...")
            return None
        return gmod_dir

    def auto_or_prompt_whitelist(self, content_folder: str) -> tuple[str | None, bool]:
        root_folder = PROJECT_ROOT
        auto_whitelist_file = os.path.join(root_folder, 'whitelist.txt')
        if os.path.exists(auto_whitelist_file):
            return (auto_whitelist_file, False)
        if not self.ask_yes_no('Whitelist file', 'No whitelist.txt was found next to the app. Do you want to select a whitelist file manually?'):
            return (None, False)
        whitelist_file = self.ask_file('Select whitelist file', 'Text files (*.txt);;All files (*.*)')
        if whitelist_file and os.path.exists(whitelist_file):
            return (whitelist_file, True)
        QtWidgets.QMessageBox.warning(self, 'Invalid whitelist file', "The selected whitelist file doesn't exist.")
        return (None, False)

    def load_whitelist(self, whitelist_path: str, content_folder: str) -> set:
        """Load whitelist file and return a set of normalized file paths (relative to content folder).
        
        The whitelist file should contain one file path per line. Paths can be:
        - Relative to the content folder (e.g., "models/player.mdl")
        - Absolute paths (will be converted to relative)
        - Comments starting with # are ignored
        - Empty lines are ignored
        """
        whitelist = set()
        if not whitelist_path or not os.path.exists(whitelist_path):
            return whitelist
        try:
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if os.path.isabs(line):
                        try:
                            rel_path = os.path.relpath(line, content_folder)
                            normalized = rel_path.replace('\\', '/').lower()
                        except ValueError:
                            normalized = line.replace('\\', '/').lower()
                    else:
                        normalized = line.replace('\\', '/').lower().strip('/')
                    if normalized:
                        whitelist.add(normalized)
        except Exception as e:
            print(f'Warning: Could not load whitelist file: {e}')
        return whitelist

    def ask_merge_workflow_options(self) -> dict | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Addon Merge Options')
        layout = QtWidgets.QVBoxLayout(dialog)
        form_layout = QtWidgets.QGridLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(8)
        pack_size_spin = QtWidgets.QDoubleSpinBox()
        pack_size_spin.setRange(0.1, 100.0)
        pack_size_spin.setDecimals(2)
        pack_size_spin.setSingleStep(0.1)
        pack_size_spin.setValue(3.9)
        pack_size_spin.setSuffix(' GB')
        pack_size_spin.setToolTip('Maximum size for each generated content pack when splitting is enabled.')
        merge_only_checkbox = QtWidgets.QCheckBox('Only merge into the destination root')
        merge_only_checkbox.setToolTip('Skip pack creation and only merge the addon folders into the destination folder.')
        remove_source_addons_checkbox = QtWidgets.QCheckBox('Delete the original source addon folders after processing')
        remove_source_addons_checkbox.setToolTip('Permanently removes the top-level addon folders from the source location after the workflow finishes.')
        remove_presplit_files_checkbox = QtWidgets.QCheckBox('Delete the merged root files after creating split packs')
        remove_presplit_files_checkbox.setToolTip('After pack folders are created, remove the unsplit files that remain directly in the destination root.')

        def sync_state():
            merge_only = merge_only_checkbox.isChecked()
            pack_size_spin.setEnabled(not merge_only)
            remove_presplit_files_checkbox.setEnabled(not merge_only)
            if merge_only:
                remove_presplit_files_checkbox.setChecked(False)
        merge_only_checkbox.toggled.connect(sync_state)
        sync_state()
        form_layout.addWidget(QtWidgets.QLabel('Content Pack Size:'), 0, 0)
        form_layout.addWidget(pack_size_spin, 0, 1)
        form_layout.addWidget(merge_only_checkbox, 1, 0, 1, 2)
        form_layout.addWidget(remove_source_addons_checkbox, 2, 0, 1, 2)
        form_layout.addWidget(remove_presplit_files_checkbox, 3, 0, 1, 2)
        layout.addLayout(form_layout)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        return {'pack_size_gb': pack_size_spin.value(), 'merge_only': merge_only_checkbox.isChecked(), 'remove_source_addons': remove_source_addons_checkbox.isChecked(), 'remove_presplit_files': remove_presplit_files_checkbox.isChecked()}

    def ask_unused_materials_options(self) -> dict | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Unused Material Options')
        layout = QtWidgets.QVBoxLayout(dialog)
        description = QtWidgets.QLabel('Compare model materials against the models referenced in Lua.\nYou can save a report only, or remove the unused materials as well.')
        description.setWordWrap(True)
        layout.addWidget(description)
        remove_checkbox = QtWidgets.QCheckBox('Remove unused materials after scanning')
        remove_checkbox.setToolTip('Deletes the unused .vmt and .vtf files that are found.')
        layout.addWidget(remove_checkbox)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        return {'remove': remove_checkbox.isChecked()}

    def ask_full_workflow_options(self) -> dict | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Full Workflow Options')
        dialog.resize(520, 420)
        layout = QtWidgets.QVBoxLayout(dialog)
        description = QtWidgets.QLabel('Choose any full-workflow steps you want to skip. Leave everything unchecked to run the standard full workflow.')
        description.setWordWrap(True)
        layout.addWidget(description)
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll_contents = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_contents)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)
        step_checkboxes = {}
        for step_key, step_label in FULL_WORKFLOW_STEPS:
            checkbox = QtWidgets.QCheckBox(f'Skip: {step_label}')
            step_checkboxes[step_key] = checkbox
            scroll_layout.addWidget(checkbox)
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_contents)
        layout.addWidget(scroll_area)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        excluded_steps = {step_key for step_key, checkbox in step_checkboxes.items() if checkbox.isChecked()}
        if len(excluded_steps) == len(FULL_WORKFLOW_STEPS):
            QtWidgets.QMessageBox.warning(self, 'No workflow steps selected', 'At least one full-workflow step must remain enabled.')
            return self.ask_full_workflow_options()
        return {'excluded_steps': excluded_steps}

    def build_full_workflow_summary_lines(self, content_folder: str, gmod_folder: str, excluded_steps: set[str] | None=None, benchmark: bool=False) -> list[str]:
        excluded_steps = excluded_steps or set()
        active_steps = [label for step_key, label in FULL_WORKFLOW_STEPS if step_key not in excluded_steps]
        skipped_steps = [label for step_key, label in FULL_WORKFLOW_STEPS if step_key in excluded_steps]
        summary_lines = [f"Content folder: '{content_folder}'", f"GMod folder: '{gmod_folder}'", '']
        if benchmark:
            summary_lines.extend(['This benchmark will:', '1. Clone the content folder to a temporary benchmark location', '2. Run the selected full-workflow steps on the clone', '3. Measure before/after folder size', '4. Delete the benchmark clone afterwards', ''])
        summary_lines.append('Included steps:')
        summary_lines.extend(f'{index}. {label}' for index, label in enumerate(active_steps, start=1))
        if skipped_steps:
            summary_lines.extend(['', 'Skipped steps:'])
            summary_lines.extend(f'- {label}' for label in skipped_steps)
        if 'missing_materials_report' not in excluded_steps:
            summary_lines.extend(['', 'Reports will be saved in the project root.'])
        return summary_lines

    def ask_int(self, title: str, label: str, default: int=1024) -> int | None:
        value, ok = QtWidgets.QInputDialog.getInt(self, title, label, value=default, minValue=1, maxValue=10000000, step=1)
        return value if ok else None

    def ask_yes_no(self, title: str, text: str) -> bool:
        res = QtWidgets.QMessageBox.question(self, title, text, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        return res == QtWidgets.QMessageBox.Yes

    def ensure_ffmpeg_for_action(self, action_name: str) -> bool:
        return _ensure_ffmpeg_for_action(self, action_name)

    def ask_file(self, title: str, filter_str: str) -> str | None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, filter=filter_str)
        return path or None

    def ask_directory(self, title: str) -> str | None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, title)
        return path or None

    def folder_label_for_backup_kind(self, kind: str) -> str:
        labels = {'content_folder': 'Content Folder', 'content_packs': 'Content Packs'}
        return labels.get(kind, 'Folder')

    def backup_root_for_kind(self, kind: str) -> str:
        roots = {'content_folder': os.path.join(PROJECT_ROOT, 'backups', 'content_folder'), 'content_packs': os.path.join(PROJECT_ROOT, 'backups', 'content_packs')}
        return roots[kind]

    def backup_status_label_for_kind(self, kind: str) -> QtWidgets.QLabel:
        labels = {'content_folder': self.content_folder_backup_label, 'content_packs': self.content_packs_backup_label}
        return labels[kind]

    def configured_folder_for_backup_kind(self, kind: str) -> str | None:
        if kind == 'content_folder':
            path = self.content_folder_edit.text().strip()
        elif kind == 'content_packs':
            path = self.content_packs_edit.text().strip()
        else:
            path = ''
        if path and os.path.isdir(path):
            if kind == 'content_folder':
                self.remember_content_folder(path)
            return path
        QtWidgets.QMessageBox.warning(self, 'Folder missing', f'Please choose a valid {self.folder_label_for_backup_kind(kind)} folder first.')
        return None

    def ask_backup_folder(self, kind: str) -> str | None:
        backup_root = self.backup_root_for_kind(kind)
        os.makedirs(backup_root, exist_ok=True)
        path = QtWidgets.QFileDialog.getExistingDirectory(self, f'Select {self.folder_label_for_backup_kind(kind)} backup', backup_root)
        return path or None

    def folder_contains_path(self, parent: str, child: str) -> bool:
        try:
            common = os.path.commonpath([os.path.abspath(parent), os.path.abspath(child)])
            return common == os.path.abspath(parent)
        except ValueError:
            return False

    def remove_folder_contents(self, folder: str):
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    def latest_backup_folder(self, kind: str) -> str | None:
        backup_root = self.backup_root_for_kind(kind)
        if not os.path.isdir(backup_root):
            return None
        backup_folders = []
        for name in os.listdir(backup_root):
            path = os.path.join(backup_root, name)
            if os.path.isdir(path):
                try:
                    modified = os.path.getmtime(path)
                except OSError:
                    continue
                backup_folders.append((modified, path))
        if not backup_folders:
            return None
        backup_folders.sort(key=lambda item: item[0], reverse=True)
        return backup_folders[0][1]

    def refresh_backup_status_labels(self):
        for kind in ('content_folder', 'content_packs'):
            label = self.backup_status_label_for_kind(kind)
            latest = self.latest_backup_folder(kind)
            title = self.folder_label_for_backup_kind(kind)
            if latest:
                try:
                    timestamp = datetime.fromtimestamp(os.path.getmtime(latest)).strftime('%Y-%m-%d %H:%M:%S')
                except OSError:
                    timestamp = 'Unknown'
                label.setText(f'Last {title} backup: {timestamp}')
            else:
                label.setText(f'Last {title} backup: No backups yet')
            label.setStyleSheet('QLabel { color: #aaaaaa; padding-top: 2px; }')

    def copy_folder_with_progress(self, source: str, destination: str, progress_callback=None):
        files_to_copy = []
        for root, _, files in os.walk(source):
            for filename in files:
                files_to_copy.append((root, filename))
        total = len(files_to_copy)
        copied = 0
        if progress_callback:
            progress_callback(0, total)
        os.makedirs(destination, exist_ok=True)
        for root, filename in files_to_copy:
            src_path = os.path.join(root, filename)
            rel_path = os.path.relpath(src_path, source)
            dst_path = os.path.join(destination, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            copied += 1
            if progress_callback:
                progress_callback(copied, total)

    def create_folder_backup(self, source_folder: str, kind: str):
        backup_root = self.backup_root_for_kind(kind)
        os.makedirs(backup_root, exist_ok=True)
        folder_name = os.path.basename(os.path.normpath(source_folder)) or 'folder'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_folder = os.path.join(backup_root, f'{folder_name}_{timestamp}')
        print(f"Creating backup of '{source_folder}'")
        print(f'Backup destination: {backup_folder}')
        self.copy_folder_with_progress(source_folder, backup_folder, progress_callback=self.worker.progress.emit)
        print('Backup completed successfully.')
        return backup_folder

    def restore_folder_backup(self, backup_folder: str, target_folder: str):
        if not os.path.isdir(backup_folder):
            raise FileNotFoundError(f'Backup folder does not exist: {backup_folder}')
        if not os.path.isdir(target_folder):
            raise FileNotFoundError(f'Target folder does not exist: {target_folder}')
        backup_folder_abs = os.path.abspath(backup_folder)
        target_folder_abs = os.path.abspath(target_folder)
        if backup_folder_abs == target_folder_abs:
            raise ValueError('Backup folder and target folder cannot be the same folder.')
        if self.folder_contains_path(target_folder_abs, backup_folder_abs):
            raise ValueError('The selected backup is inside the target folder. Choose a backup stored elsewhere.')
        print(f"Restoring backup from '{backup_folder}'")
        print(f'Target folder: {target_folder}')
        print('Clearing existing target folder contents...')
        self.remove_folder_contents(target_folder)
        print('Copying backup files into target folder...')
        self.copy_folder_with_progress(backup_folder, target_folder, progress_callback=self.worker.progress.emit)
        print('Backup restored successfully.')

    def validate_full_workflow_fields(self) -> tuple[str, str] | None:
        content_folder = self.content_folder_edit.text().strip()
        gmod_folder = self.gmod_folder_edit.text().strip()
        issues = []
        if not content_folder:
            issues.append('Content Folder is empty.')
        elif not os.path.isdir(content_folder):
            issues.append('Content Folder must point to an existing folder.')
        if not gmod_folder:
            issues.append('GMod Folder is empty.')
        elif not os.path.exists(os.path.join(gmod_folder, 'gmod.exe')):
            issues.append("GMod Folder must point to a Garry's Mod install that contains gmod.exe.")
        if issues:
            QtWidgets.QMessageBox.warning(self, 'Missing workflow fields', 'Fill out the required fields before starting the full workflow:\n\n' + '\n'.join(issues))
            return None
        self.remember_content_folder(content_folder)
        return (content_folder, gmod_folder)

    def start_task(self, description: str, fn, *args, determinate: bool=False, modified_folder=None, **kwargs):
        if self.thread is not None:
            QtWidgets.QMessageBox.information(self, 'Busy', 'A task is already running. Please wait for it to finish.')
            return
        reset_tracker()
        self.progress.setVisible(True)
        if determinate:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        else:
            self.progress.setRange(0, 0)
        self.log_append(f'Starting: {description}\n')
        self.thread = QtCore.QThread()
        self.worker = TaskWorker(fn, *args, description=description, modified_folder=modified_folder, **kwargs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.started.connect(lambda msg: None)
        self.worker.log.connect(self.log_append)
        self.worker.progress.connect(self.on_progress_update)
        self.worker.finished.connect(self.on_task_finished)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_thread)
        self.thread.start()

    def cleanup_thread(self):
        self.thread = None
        self.worker = None
        self.progress.setVisible(False)

    def on_progress_update(self, current: int, total: int):
        """Update progress bar with current/total values"""
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        else:
            self.progress.setRange(0, 0)

    def on_task_finished(self, msg: str, modified_folder: str):
        self.log_append(msg + '\n')
        self.update_folder_size(modified_folder if modified_folder else None)
        self.generate_removal_report()

    def on_task_failed(self, msg: str, modified_folder: str):
        self.log_append(msg + '\n')
        self.update_folder_size(modified_folder if modified_folder else None)
        self.generate_removal_report()
        QtWidgets.QMessageBox.critical(self, 'Task failed', msg)

    def log_append(self, text: str):
        self.log.moveCursor(QtGui.QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QtGui.QTextCursor.End)

    def calculate_folder_size(self, folder: str) -> int:
        """Calculate total size of all files in folder"""
        total_size = 0
        try:
            for root, _, files in os.walk(folder):
                for filename in files:
                    file_path = os.path.join(root, filename)
                    try:
                        total_size += os.path.getsize(file_path)
                    except (OSError, FileNotFoundError):
                        pass
        except Exception as e:
            print(f'Error calculating folder size: {e}')
        return total_size

    def calculate_initial_folder_size(self, folder: str):
        """Calculate and store initial folder size"""
        self.size_label.setText('Calculating folder size...')
        QtWidgets.QApplication.processEvents()
        size = self.calculate_folder_size(folder)
        self.initial_folder_size = size
        self.current_folder_size = size
        self.update_size_label()

    def update_folder_size(self, modified_folder=None):
        """Recalculate folder size after an operation"""
        content_folder = self.current_content_folder()
        if not modified_folder or modified_folder == content_folder:
            if content_folder and os.path.exists(content_folder):
                self.current_folder_size = self.calculate_folder_size(content_folder)
                self.update_size_label()
        else:
            if content_folder and os.path.exists(content_folder):
                self.current_folder_size = self.calculate_folder_size(content_folder)
                self.update_size_label()
            if os.path.exists(modified_folder):
                modified_size = self.calculate_folder_size(modified_folder)
                print(f"Modified folder '{modified_folder}' size: {format_size(modified_size)}")

    def update_size_label(self):
        """Update the size label with initial and current sizes"""
        if self.initial_folder_size == 0:
            self.size_label.setText('Folder size: Not folder selected')
            return
        initial_str = format_size(self.initial_folder_size)
        current_str = format_size(self.current_folder_size)
        if self.initial_folder_size == self.current_folder_size:
            self.size_label.setText(f'Folder size: {current_str}')
        else:
            diff = self.initial_folder_size - self.current_folder_size
            diff_str = format_size(diff)
            percentage = diff / self.initial_folder_size * 100 if self.initial_folder_size > 0 else 0
            if diff > 0:
                self.size_label.setText(f"Folder size: <span style='color: #888;'>{initial_str}</span> → <b>{current_str}</b> <span style='color: #4CAF50;'>(−{diff_str}, −{percentage:.2f}%)</span>")
            else:
                self.size_label.setText(f"Folder size: <span style='color: #888;'>{initial_str}</span> → <b>{current_str}</b> <span style='color: #f44336;'>(+{format_size(-diff)})</span>")
        self.size_label.setTextFormat(QtCore.Qt.RichText)

    def generate_removal_report(self):
        """Generate a markdown report of all removed files."""
        tracker = get_tracker()
        summary = tracker.get_summary()
        if summary['total_files'] > 0 or summary['total_directories'] > 0:
            root_folder = PROJECT_ROOT
            report_path = os.path.join(root_folder, 'removed_files_report.md')
            content_folder = self.current_content_folder()
            tracker.generate_markdown_report(report_path, content_folder)

    def on_scan_unused_model_formats(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                size, count = unused_model_formats(addon_path, False, progress_callback=self.worker.progress.emit)
                print(f'Found {count} unused model formats, taking up {format_size(size)}')
                return (size, count)
            return self.run_content_targets(folder, 'Scan unused model formats', run_for_addon)
        self.start_task('Scan unused model formats', task, determinate=True, modified_folder=folder)

    def on_remove_unused_model_formats(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                size, count = unused_model_formats(addon_path, True, progress_callback=self.worker.progress.emit)
                print(f'Removed {count} unused model formats, saving {format_size(size)}')
                return (size, count)
            return self.run_content_targets(folder, 'Remove unused model formats', run_for_addon)
        self.start_task('Remove unused model formats', task, determinate=True, modified_folder=folder)

    def run_unused_material_textures(self, remove_unused_materials: bool):
        folder = self.ensure_content_folder('Select content folder to scan for unused model materials')
        if not folder:
            return
        root_folder = PROJECT_ROOT
        whitelist_file, manual_whitelist = self.auto_or_prompt_whitelist(folder)
        use_whitelist = bool(whitelist_file and os.path.exists(whitelist_file))
        unused_materials_report = os.path.join(root_folder, 'unused_material_textures_report.txt')
        backup_dir = None
        if remove_unused_materials:
            content_name = os.path.basename(os.path.normpath(folder)) or 'content'
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_dir = os.path.join(root_folder, 'backups', 'unused_material_textures', f'{content_name}_{timestamp}')

        def task():

            def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
                whitelist = self.load_whitelist(whitelist_file, addon_path) if use_whitelist else None
                if whitelist:
                    source_type = 'manual' if manual_whitelist else 'auto-detected'
                    print(f'Loaded {len(whitelist)} whitelist entries from {source_type} whitelist file')
                elif manual_whitelist and whitelist_file:
                    print(f"Warning: Manual whitelist file '{whitelist_file}' was specified but could not be loaded")
                elif whitelist_file:
                    print(f"Warning: Auto-detected whitelist file '{whitelist_file}' exists but could not be loaded")
                else:
                    print('No whitelist file found or specified - proceeding without whitelist')
                addon_report = self.build_addon_output_file(unused_materials_report, addon_name, is_multi)
                addon_backup_dir = None
                if backup_dir:
                    addon_backup_dir = self.build_addon_output_folder(backup_dir, addon_name, is_multi)
                size, count = unused_content(addon_path, remove=remove_unused_materials, whitelist=whitelist, save_unused_to=addon_report, progress_callback=self.worker.progress.emit, materials_only=True, textures_only=True, backup_dir=addon_backup_dir)
                if remove_unused_materials:
                    print(f'Removed {count} unused material texture files, saving {format_size(size)}')
                    if addon_backup_dir:
                        print(f'Backup saved to: {addon_backup_dir}')
                else:
                    print(f'Found {count} unused material texture files, totaling {format_size(size)}')
                print(f'Unused material textures list saved to: {addon_report}')
                return (size, count)
            return self.run_content_targets(folder, description, run_for_addon)
        description = 'Remove unused material textures' if remove_unused_materials else 'Find unused material textures'
        self.start_task(description, task, determinate=True, modified_folder=folder)

    def on_find_unused_materials(self):
        self.run_unused_material_textures(False)

    def on_remove_unused_materials(self):
        self.run_unused_material_textures(True)

    def on_remove_game_files(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        remove = self.ask_yes_no('Remove files?', 'Do you want to remove the found files? This will remove files that are already provided by the game.')
        preset_gmod = self.current_gmod_folder()
        if preset_gmod and os.path.exists(os.path.join(preset_gmod, 'gmod.exe')):
            gamefolder = preset_gmod
        else:
            gamefolder = self.ask_directory('Absolute path to game folder (eg C:/Program Files (x86)/Steam/steamapps/common/GarrysMod)')
            if not gamefolder or not os.path.exists(os.path.join(gamefolder, 'gmod.exe')):
                QtWidgets.QMessageBox.warning(self, 'Invalid game folder', "The selected folder doesn't contain gmod.exe")
                return

        def task():

            def run_for_addon(addon_path, *_args):
                remove_game_files(addon_path, gamefolder, remove)
                return (0, 0)
            return self.run_content_targets(folder, 'Remove files already in game', run_for_addon)
        self.start_task('Remove files already in game', task, modified_folder=folder)

    def on_remove_empty_folders(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                removed = remove_empty_folders(addon_path, progress_callback=self.worker.progress.emit)
                return (0, removed)
            return self.run_content_targets(folder, 'Remove empty folders', run_for_addon)
        self.start_task('Remove empty folders', task, determinate=True, modified_folder=folder)

    def run_folder_backup(self, kind: str):
        source_folder = self.configured_folder_for_backup_kind(kind)
        if not source_folder:
            return

        def task():
            backup_folder = self.create_folder_backup(source_folder, kind)
            print(f'Saved backup to: {backup_folder}')
        self.start_task(f'Back up {self.folder_label_for_backup_kind(kind)}', task, determinate=True, modified_folder=source_folder)
        if self.thread is not None:
            self.thread.finished.connect(self.refresh_backup_status_labels)

    def run_folder_restore(self, kind: str):
        target_folder = self.configured_folder_for_backup_kind(kind)
        if not target_folder:
            return
        backup_folder = self.ask_backup_folder(kind)
        if not backup_folder:
            return
        label = self.folder_label_for_backup_kind(kind)
        warning = f'This will replace everything inside the current {label} folder with the selected backup.\n\nCurrent folder:\n{target_folder}\n\nBackup folder:\n{backup_folder}\n\nContinue?'
        if not self.ask_yes_no(f'Load {label} backup?', warning):
            return

        def task():
            self.restore_folder_backup(backup_folder, target_folder)
        self.start_task(f'Load {label} backup', task, determinate=True, modified_folder=target_folder)

    def on_backup_content_folder(self):
        self.run_folder_backup('content_folder')

    def on_restore_content_folder_backup(self):
        self.run_folder_restore('content_folder')

    def on_backup_content_packs(self):
        self.run_folder_backup('content_packs')

    def on_restore_content_packs_backup(self):
        self.run_folder_restore('content_packs')

    def on_clamp_vtf(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        size = self.ask_int('Clamp VTF size', 'Clamp size (pixels)', default=1024)
        if size is None:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return resize_and_compress(addon_path, int(size), progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Clamp VTF file sizes', run_for_addon)
        self.start_task('Clamp VTF file sizes', task, determinate=True, modified_folder=folder)

    def on_use_dxt(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return resize_and_compress(addon_path, 1000000, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Use DXT for VTFs', run_for_addon)
        self.start_task('Use DXT for VTFs', task, determinate=True, modified_folder=folder)

    def on_remove_mipmaps(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return remove_mipmaps(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Remove mipmaps', run_for_addon)
        self.start_task('Remove mipmaps', task, determinate=True, modified_folder=folder)

    def on_clamp_png(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        size = self.ask_int('Clamp PNG size', 'Clamp size (pixels)', default=512)
        if size is None:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return clamp_pngs(addon_path, int(size), progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Clamp PNG file sizes', run_for_addon)
        self.start_task('Clamp PNG file sizes', task, determinate=True, modified_folder=folder)

    def on_sounds_to_ogg(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Convert sound to OGG'):
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return sounds_to_ogg(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Convert sound to OGG', run_for_addon)
        self.start_task('Convert sound to OGG', task, determinate=True, modified_folder=folder)

    def on_trim_empty_audio(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Trim silence'):
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return trim_empty_audio(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Trim silence', run_for_addon)
        self.start_task('Trim silence', task, determinate=True, modified_folder=folder)

    def on_reencode_oggs(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Re-encode existing OGGs'):
            return
        bitrate = self.ask_int('Re-encode OGGs', 'Target bitrate (kbps)', default=96)
        if bitrate is None:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return reencode_oggs(addon_path, bitrate_kbps=bitrate, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Re-encode existing OGGs', run_for_addon)
        self.start_task('Re-encode existing OGGs', task, determinate=True, modified_folder=folder)

    def on_resample_oggs(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Resample'):
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return resample_oggs(addon_path, target_rate=44100, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Resample', run_for_addon)
        self.start_task('Resample', task, determinate=True, modified_folder=folder)

    def on_normalize_audio(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Normalize the volume'):
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return normalize_audio(addon_path, target_lufs=-14.0, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Normalize the volume', run_for_addon)
        self.start_task('Normalize the volume', task, determinate=True, modified_folder=folder)

    def on_strip_audio_metadata(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Strip metadata from audio'):
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return strip_audio_metadata(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Strip audio metadata', run_for_addon)
        self.start_task('Strip metadata from audio', task, determinate=True, modified_folder=folder)

    def on_run_full_sound_workflow(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Run Full Sound Workflow'):
            return
        summary_lines = [f"Content folder: '{folder}'", '', 'This workflow will:', '1. Convert sound files to OGG', '2. Resample unsupported OGG sample rates', '3. Strip audio metadata']
        if not self.ask_yes_no('Run full sound workflow?', '\n'.join(summary_lines)):
            return
        self.start_task('Full sound workflow', lambda: self.run_full_sound_workflow_task(folder), determinate=True, modified_folder=folder)

    def on_convert_to_png(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return convert_images_to_png(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Convert images to PNG', run_for_addon)
        self.start_task('Convert images to PNG', task, determinate=True, modified_folder=folder)

    def on_convert_dds_to_png(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Convert DDS to PNG'):
            return
        delete = self.ask_yes_no('Delete originals?', 'Delete the original DDS files after converting to PNG?')

        def task():

            def run_for_addon(addon_path, *_args):
                return convert_dds_to_png(addon_path, delete_originals=delete, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Convert DDS to PNG', run_for_addon)
        self.start_task('Convert DDS to PNG', task, determinate=True, modified_folder=folder)

    def on_remove_png_ports(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                return remove_png_ports(addon_path, progress_callback=self.worker.progress.emit)
            return self.run_content_targets(folder, 'Remove PNG Ports', run_for_addon)
        self.start_task('Remove PNG Ports', task, determinate=True, modified_folder=folder)

    def on_run_full_image_workflow(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Run Full Image Workflow'):
            return
        summary_lines = [f"Content folder: '{folder}'", '', 'This workflow will:', '1. Convert DDS files to PNG', '2. Convert images to PNG', '3. Convert VTF files to DXT', '4. Clamp VTF file sizes to 1024px', '5. Remove mipmaps', '6. Resave VTF files (autorefresh)', '7. Clamp PNG files to 512px']
        if not self.ask_yes_no('Run full image workflow?', '\n'.join(summary_lines)):
            return
        self.start_task('Full image workflow', lambda: self.run_full_image_workflow_task(folder), determinate=True, modified_folder=folder)

    def on_find_map_content(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        preset_gmod = self.current_gmod_folder()
        if preset_gmod and os.path.exists(os.path.join(preset_gmod, 'gmod.exe')):
            gamefolder = preset_gmod
        else:
            gamefolder = self.ask_directory('Absolute path to game folder (eg C:/Program Files (x86)/Steam/steamapps/common/GarrysMod)')
            if not gamefolder or not os.path.exists(os.path.join(gamefolder, 'gmod.exe')):
                QtWidgets.QMessageBox.warning(self, 'Invalid game folder', "The selected folder doesn't contain gmod.exe")
                return
        map_file = self.ask_file('Select .bsp map file', 'BSP files (*.bsp)')
        if not map_file or not map_file.endswith('.bsp'):
            QtWidgets.QMessageBox.warning(self, 'Invalid map file', 'Please select a valid .bsp file.')
            return
        dest_folder = self.ask_directory("Folder to copy found content to (will be created if it doesn't exist)")
        if not dest_folder:
            QtWidgets.QMessageBox.warning(self, 'Invalid destination', 'Please select a destination folder.')
            return
        os.makedirs(dest_folder, exist_ok=True)

        def task():

            def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
                addon_dest = self.build_addon_output_folder(dest_folder, addon_name, is_multi)
                os.makedirs(addon_dest, exist_ok=True)
                find_map_content(addon_path, gamefolder, addon_dest, map_file)
                return (0, 0)
            return self.run_content_targets(folder, 'Find/copy content used by map', run_for_addon)
        self.start_task('Find/copy content used by map', task, modified_folder=dest_folder)

    def on_find_missing_materials(self):
        folder = self.ensure_content_folder('Select content folder to scan for missing materials')
        if not folder:
            return
        root_folder = PROJECT_ROOT
        default_output = os.path.join(root_folder, 'missing_materials_report.md')
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save Missing Materials Report', default_output, 'Markdown files (*.md);;All files (*.*)')
        if not output_path:
            return
        gmod_dir = self.ask_optional_gmod_dir("Do you want to specify a Garry's Mod directory for fallback resources?\nThis helps avoid flagging base-game materials as missing.")

        def task():

            def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
                addon_output_path = self.build_addon_output_file(output_path, addon_name, is_multi)
                total_models, models_with_materials, total_materials, missing_materials = extract_missing_materials_to_markdown(addon_path, addon_output_path, gmod_dir=gmod_dir, progress_callback=self.worker.progress.emit)
                print(f'Scanned {total_models} models')
                print(f'  - {models_with_materials} models have materials')
                print(f'  - {total_materials} total material directories found')
                print(f'  - {missing_materials} missing material directories')
                print(f'Report saved to: {addon_output_path}')
                return (0, missing_materials)
            return self.run_content_targets(folder, 'Find missing materials', run_for_addon)
        self.start_task('Find missing materials', task, determinate=True)

    def on_recover_missing_materials(self):
        folder = self.ensure_content_folder('Select the main content folder to recover materials into')
        if not folder:
            return
        preset_packs = self.content_packs_edit.text().strip()
        if preset_packs and os.path.isdir(preset_packs):
            search_root = preset_packs
        else:
            search_root = self.ask_directory('Select the folder containing content-pack subfolders')
            if not search_root or not os.path.exists(search_root):
                QtWidgets.QMessageBox.warning(self, 'Search root required', 'Please select a valid content-pack search root.')
                return
        root_folder = PROJECT_ROOT
        default_output = os.path.join(root_folder, 'missing_materials_recovery_report.md')
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save Missing Materials Recovery Report', default_output, 'Markdown files (*.md);;All files (*.*)')
        if not output_path:
            return
        gmod_dir = self.ask_optional_gmod_dir("Do you want to specify a Garry's Mod directory for fallback resources?\nThis helps avoid copying materials that already exist in base Garry's Mod.")

        def task():

            def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
                addon_output_path = self.build_addon_output_file(output_path, addon_name, is_multi)
                copied_size, copied_count, missing_count, found_matches, still_missing_dirs = recover_missing_materials_from_content_packs(addon_path, search_root, addon_output_path, gmod_dir=gmod_dir, progress_callback=self.worker.progress.emit)
                print(f'Scanned {missing_count} missing material files')
                print(f'  - {found_matches} matches found in content packs')
                print(f'  - {copied_count} files copied into the content folder')
                print(f'  - {still_missing_dirs} cdmaterials directories are still missing after verification')
                print(f'Report saved to: {addon_output_path}')
                return (copied_size, copied_count)
            return self.run_content_targets(folder, 'Recover missing materials', run_for_addon)
        self.start_task('Recover missing materials', task, determinate=True, modified_folder=folder)

    def on_find_models_with_missing_textures(self):
        folder = self.ensure_content_folder('Select content folder to scan for models with missing textures')
        if not folder:
            return
        root_folder = PROJECT_ROOT
        default_output = os.path.join(root_folder, 'missing_texture_models_report.md')
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save Missing Texture Models Report', default_output, 'Markdown files (*.md);;All files (*.*)')
        if not output_path:
            return
        gmod_dir = self.ask_optional_gmod_dir("Do you want to specify a Garry's Mod directory for fallback resources?\nThis helps avoid flagging models whose materials ship with the base game.")

        def task():

            def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
                addon_output_path = self.build_addon_output_file(output_path, addon_name, is_multi)
                _, count = remove_models_with_missing_materials(addon_path, gmod_dir=gmod_dir, remove=False, output_path=addon_output_path, progress_callback=self.worker.progress.emit)
                return (0, count)
            return self.run_content_targets(folder, 'Find models with missing textures', run_for_addon)
        self.start_task('Find models with missing textures', task, determinate=True)

    def on_remove_comments(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        remove = self.ask_yes_no('Remove comments?', 'Do you want to remove comments from all Lua files in the content folder?\nThis will remove single-line and inline comments while preserving long comment blocks.')
        if not remove:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                size_saved, files_processed = remove_comments_from_directory(addon_path)
                print(f'Removed comments from {files_processed} Lua files, saving {format_size(size_saved)}')
                return (size_saved, files_processed)
            return self.run_content_targets(folder, 'Remove comments from Lua files', run_for_addon)
        self.start_task('Remove comments from Lua files', task, modified_folder=folder)

    def on_resave_vtf(self):
        folder = self.ensure_content_folder()
        if not folder:
            return

        def task():

            def run_for_addon(addon_path, *_args):
                count = self.resave_vtf_files(addon_path)
                print(f'Resaved {count} VTF files.')
                return (0, count)
            return self.run_content_targets(folder, 'Resave VTF files', run_for_addon)
        self.start_task('Resave VTF files', task, modified_folder=folder)

    def on_run_addon_merge_workflow(self):
        preset_source = self.addon_source_edit.text().strip()
        if preset_source and os.path.isdir(preset_source):
            addon_source = preset_source
        else:
            addon_source = self.ask_directory('Select the folder that contains the addon folders to merge')
            if not addon_source or not os.path.exists(addon_source):
                QtWidgets.QMessageBox.warning(self, 'Addon source missing', 'Please choose a valid addon source folder.')
                return
        preset_output = self.addon_output_edit.text().strip()
        if preset_output and preset_output.strip():
            addon_output = preset_output
        else:
            addon_output = self.ask_directory('Select the merged output folder / pack root')
            if not addon_output:
                QtWidgets.QMessageBox.warning(self, 'Output folder missing', 'Please choose a valid merged output folder.')
                return
        os.makedirs(addon_output, exist_ok=True)
        options = self.ask_merge_workflow_options()
        if not options:
            return
        pack_size_gb = options['pack_size_gb']
        merge_only = options['merge_only']
        remove_source_addons = options['remove_source_addons']
        remove_presplit_files = options['remove_presplit_files']
        summary_lines = [f"Source addon folder: '{addon_source}'", f"Merged output folder: '{addon_output}'", f"Mode: {('Merge only' if merge_only else f'Merge and split into packs of {pack_size_gb:.2f} GB')}", f"Delete source addon folders after processing: {('Yes' if remove_source_addons else 'No')}", f"Delete merged root files after splitting: {('Yes' if remove_presplit_files else 'No')}"]
        if remove_source_addons or remove_presplit_files:
            summary_lines.append('')
            summary_lines.append('Checked deletion options permanently remove files.')
        if not self.ask_yes_no('Run addon merge workflow?', '\n'.join(summary_lines)):
            return

        def task():
            merge_addon_workflow(addon_source, addon_output, pack_size_gb=pack_size_gb, remove_source_addon_folders=remove_source_addons, merge_only=merge_only, remove_pre_split_files=remove_presplit_files, progress_callback=self.worker.progress.emit)
            print('Addon merge workflow completed successfully')
        self.start_task('Addon merge workflow', task, determinate=True, modified_folder=addon_output)

    def on_extract_content_packs(self):
        preset_packs = self.content_packs_edit.text().strip()
        if preset_packs and os.path.isdir(preset_packs):
            packs_folder = preset_packs
        else:
            packs_folder = self.ask_directory('Select the folder containing content-pack subfolders')
            if not packs_folder or not os.path.exists(packs_folder):
                QtWidgets.QMessageBox.warning(self, 'Packs folder missing', 'Please choose a valid content-pack source folder.')
                return
        content_folder = self.ensure_content_folder('Select the content folder to import content packs into')
        if not content_folder:
            return
        warning_msg = f"This will scan each subfolder inside '{packs_folder}', detect its content root, and copy its content files into '{content_folder}'.\n\nExisting files may be overwritten. Continue?"
        if not self.ask_yes_no('Extract content packs?', warning_msg):
            return

        def task():
            copied_files, total_files = extract_content_packs(packs_folder, content_folder, progress_callback=self.worker.progress.emit)
            print(f"Extracted {copied_files} files from content packs into '{content_folder}'")
            return (0, copied_files)
        self.start_task('Extract content packs', task, determinate=True, modified_folder=content_folder)

    def on_run_full_workflow(self):
        validated = self.validate_full_workflow_fields()
        if not validated:
            return
        if not self.ensure_ffmpeg_for_action('Run Full Workflow (Except Merge)'):
            return
        options = self.ask_full_workflow_options()
        if not options:
            return
        content_folder, gmod_folder = validated
        missing_materials_report = os.path.join(PROJECT_ROOT, 'missing_materials_report.md')
        excluded_steps = options['excluded_steps']
        summary_lines = self.build_full_workflow_summary_lines(content_folder, gmod_folder, excluded_steps=excluded_steps)
        if not self.ask_yes_no('Run full workflow?', '\n'.join(summary_lines)):
            return
        self.start_task('Full workflow (except merge)', lambda: self.run_full_workflow_task(content_folder, gmod_folder, missing_materials_report, excluded_steps=excluded_steps), modified_folder=content_folder)

    def on_benchmark_full_image_workflow(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Benchmark Textures'):
            return
        summary_lines = [f"Content folder: '{folder}'", '', 'This benchmark will:', '1. Clone the content folder to a temporary benchmark location', '2. Run the textures workflow on the clone', '3. Measure before/after folder size', '4. Delete the benchmark clone afterwards']
        if not self.ask_yes_no('Run textures benchmark?', '\n'.join(summary_lines)):
            return
        self.start_task('Benchmark textures', lambda: self.run_benchmark_workflow_task(folder, 'Textures', lambda clone_folder: self.run_full_image_workflow_task(clone_folder)), determinate=True)

    def on_benchmark_cleanup_workflow(self):
        validated = self.validate_full_workflow_fields()
        if not validated:
            return
        content_folder, gmod_folder = validated
        summary_lines = [f"Content folder: '{content_folder}'", f"GMod folder: '{gmod_folder}'", '', 'This benchmark will:', '1. Clone the content folder to a temporary benchmark location', '2. Run the cleanup workflow on the clone', '3. Measure before/after folder size', '4. Delete the benchmark clone afterwards']
        if not self.ask_yes_no('Run cleanup benchmark?', '\n'.join(summary_lines)):
            return
        self.start_task('Benchmark cleanup', lambda: self.run_benchmark_workflow_task(content_folder, 'Cleanup', lambda clone_folder: self.run_cleanup_workflow_task(clone_folder, gmod_folder)), determinate=True)

    def on_benchmark_full_sound_workflow(self):
        folder = self.ensure_content_folder()
        if not folder:
            return
        if not self.ensure_ffmpeg_for_action('Benchmark Audio'):
            return
        summary_lines = [f"Content folder: '{folder}'", '', 'This benchmark will:', '1. Clone the content folder to a temporary benchmark location', '2. Run the audio workflow on the clone', '3. Measure before/after folder size', '4. Delete the benchmark clone afterwards']
        if not self.ask_yes_no('Run audio benchmark?', '\n'.join(summary_lines)):
            return
        self.start_task('Benchmark audio', lambda: self.run_benchmark_workflow_task(folder, 'Audio', lambda clone_folder: self.run_full_sound_workflow_task(clone_folder)), determinate=True)

    def on_benchmark_full_workflow(self):
        validated = self.validate_full_workflow_fields()
        if not validated:
            return
        if not self.ensure_ffmpeg_for_action('Benchmark Full Workflow'):
            return
        options = self.ask_full_workflow_options()
        if not options:
            return
        content_folder, gmod_folder = validated
        excluded_steps = options['excluded_steps']
        summary_lines = self.build_full_workflow_summary_lines(content_folder, gmod_folder, excluded_steps=excluded_steps, benchmark=True)
        if not self.ask_yes_no('Run full workflow benchmark?', '\n'.join(summary_lines)):
            return
        self.start_task('Benchmark full workflow', lambda: self.run_benchmark_workflow_task(content_folder, 'Full Workflow', lambda clone_folder: self.run_full_workflow_task(clone_folder, gmod_folder, os.path.join(clone_folder, 'missing_materials_report.md'), excluded_steps=excluded_steps)), determinate=True)

    def run_cleanup_workflow_task(self, content_folder: str, gmod_folder: str):

        def run_for_addon(addon_path, *_args):
            print('')
            print('=' * 80)
            print('RUNNING CLEANUP WORKFLOW')
            print('=' * 80)
            print('\n[1/4] Removing unused model formats...')
            model_format_size, model_format_count = unused_model_formats(addon_path, True)
            print(f'Removed {model_format_count} unused model format files, saving {format_size(model_format_size)}')
            print("\n[2/4] Removing files already in Garry's Mod...")
            remove_game_files(addon_path, gmod_folder, True)
            print('\n[3/4] Removing empty folders...')
            empty_folder_count = remove_empty_folders(addon_path)
            print(f'Removed {empty_folder_count} empty folders')
            print('\n[4/4] Removing comments from Lua files...')
            comments_size, comments_count = remove_comments_from_directory(addon_path)
            print(f'Removed comments from {comments_count} Lua files, saving {format_size(comments_size)}')
            total_saved = model_format_size + comments_size
            total_files = model_format_count + comments_count + empty_folder_count
            print('\nCleanup workflow completed successfully.')
            return (total_saved, total_files)
        return self.run_content_targets(content_folder, 'Cleanup workflow', run_for_addon)

    def run_full_workflow_task(self, content_folder: str, gmod_folder: str, missing_materials_report: str, excluded_steps: set[str] | None=None):
        excluded_steps = excluded_steps or set()
        total_steps = sum(1 for step_key, _label in FULL_WORKFLOW_STEPS if step_key not in excluded_steps)

        def run_for_addon(addon_path, addon_name, _index, _total, is_multi):
            print('')
            print('=' * 80)
            print('RUNNING FULL WORKFLOW (EXCEPT MERGE)')
            print('=' * 80)
            step_number = 0
            model_format_size = 0
            model_format_count = 0
            comments_size = 0
            comments_count = 0
            empty_folder_count = 0
            if 'unused_model_formats' not in excluded_steps:
                step_number += 1
                print(f'\n[{step_number}/{total_steps}] Removing unused model formats...')
                model_format_size, model_format_count = unused_model_formats(addon_path, True)
                print(f'Removed {model_format_count} unused model format files, saving {format_size(model_format_size)}')
            if 'remove_game_files' not in excluded_steps:
                step_number += 1
                print(f"\n[{step_number}/{total_steps}] Removing files already in Garry's Mod...")
                remove_game_files(addon_path, gmod_folder, True)
            if 'remove_empty_folders' not in excluded_steps:
                step_number += 1
                print(f'\n[{step_number}/{total_steps}] Removing empty folders...')
                empty_folder_count = remove_empty_folders(addon_path)
                print(f'Removed {empty_folder_count} empty folders')
            if 'remove_comments' not in excluded_steps:
                step_number += 1
                print(f'\n[{step_number}/{total_steps}] Removing comments from Lua files...')
                comments_size, comments_count = remove_comments_from_directory(addon_path)
                print(f'Removed comments from {comments_count} Lua files, saving {format_size(comments_size)}')
            image_saved, image_counts = self.run_full_image_workflow_for_addon(addon_path, step_offset=step_number, total_steps=total_steps, excluded_steps=excluded_steps)
            dds_size = image_saved['dds_size']
            img_size = image_saved['img_size']
            dxt_size = image_saved['dxt_size']
            vtf_clamp_size = image_saved['vtf_clamp_size']
            mipmap_size = image_saved['mipmap_size']
            png_size = image_saved['png_size']
            dds_count = image_counts['dds_count']
            img_count = image_counts['img_count']
            dxt_count = image_counts['dxt_count']
            vtf_clamp_count = image_counts['vtf_clamp_count']
            mipmap_count = image_counts['mipmap_count']
            vtf_resave_count = image_counts['vtf_resave_count']
            png_count = image_counts['png_count']
            step_number += sum(1 for step_key, _label in FULL_IMAGE_WORKFLOW_STEPS if step_key not in excluded_steps)
            sound_saved, sound_counts = self.run_full_sound_workflow_for_addon(addon_path, step_offset=step_number, total_steps=total_steps, excluded_steps=excluded_steps)
            ogg_size = sound_saved['ogg_size']
            resample_size = sound_saved['resample_size']
            metadata_size = sound_saved['metadata_size']
            ogg_count = sound_counts['ogg_count']
            resample_count = sound_counts['resample_count']
            metadata_count = sound_counts['metadata_count']
            step_number += sum(1 for step_key, _label in FULL_SOUND_WORKFLOW_STEPS if step_key not in excluded_steps)
            if 'missing_materials_report' not in excluded_steps:
                step_number += 1
                addon_report = self.build_addon_output_file(missing_materials_report, addon_name, is_multi)
                print(f'\n[{step_number}/{total_steps}] Generating missing materials report...')
                total_models, models_with_materials, total_materials, missing_materials = extract_missing_materials_to_markdown(addon_path, addon_report, gmod_dir=gmod_folder)
                print(f'Scanned {total_models} models')
                print(f'  - {models_with_materials} models have materials')
                print(f'  - {total_materials} total material directories found')
                print(f'  - {missing_materials} missing material directories')
                print(f'Report saved to: {addon_report}')
            total_saved = model_format_size + comments_size + dds_size + img_size + dxt_size + vtf_clamp_size + mipmap_size + png_size + ogg_size + resample_size + metadata_size
            total_files = model_format_count + empty_folder_count + comments_count + dds_count + img_count + dxt_count + vtf_clamp_count + mipmap_count + vtf_resave_count + png_count + ogg_count + resample_count + metadata_count
            print('\nFull workflow completed successfully.')
            return (total_saved, total_files)
        return self.run_content_targets(content_folder, 'Full workflow', run_for_addon)

    def create_benchmark_clone(self, source_folder: str) -> tuple[str, str]:
        source_name = os.path.basename(os.path.normpath(source_folder)) or 'content'
        benchmark_parent = os.path.dirname(os.path.normpath(source_folder)) or None
        benchmark_root = tempfile.mkdtemp(prefix=f'{source_name}_benchmark_', dir=benchmark_parent)
        clone_folder = os.path.join(benchmark_root, source_name)
        print(f'Creating benchmark clone at: {clone_folder}')
        shutil.copytree(source_folder, clone_folder)
        return (benchmark_root, clone_folder)

    def run_benchmark_workflow_task(self, source_folder: str, workflow_name: str, workflow_runner):
        benchmark_root = None
        try:
            print('')
            print('=' * 80)
            print(f'RUNNING BENCHMARK: {workflow_name.upper()}')
            print('=' * 80)
            benchmark_root, clone_folder = self.create_benchmark_clone(source_folder)
            before_size = self.calculate_folder_size(clone_folder)
            print(f'Benchmark clone ready: {clone_folder}')
            print(f'Clone size before workflow: {format_size(before_size)}')
            workflow_runner(clone_folder)
            after_size = self.calculate_folder_size(clone_folder)
            saved_size = before_size - after_size
            saved_percent = saved_size / before_size * 100 if before_size > 0 else 0
            print('')
            print('Benchmark results:')
            print(f'  - Workflow: {workflow_name}')
            print(f'  - Before: {format_size(before_size)}')
            print(f'  - After: {format_size(after_size)}')
            if saved_size >= 0:
                print(f'  - Saved: {format_size(saved_size)} ({saved_percent:.2f}%)')
            else:
                print(f'  - Size increased by: {format_size(-saved_size)}')
            return None
        except Exception:
            reset_tracker()
            raise
        finally:
            if benchmark_root and os.path.exists(benchmark_root):
                print(f'Deleting benchmark clone: {benchmark_root}')
                shutil.rmtree(benchmark_root, ignore_errors=True)
            reset_tracker()
            print('Benchmark cleanup complete.')

    def run_full_image_workflow_task(self, content_folder: str, step_offset: int=0, total_steps: int=7):
        if self.is_addon_content_folder(content_folder):
            return self.run_full_image_workflow_for_addon(content_folder, step_offset=step_offset, total_steps=total_steps)
        return self.run_content_targets(content_folder, 'Full image workflow', lambda addon_path, *_args: self.run_full_image_workflow_for_addon(addon_path, step_offset=step_offset, total_steps=total_steps), result_mapper=lambda result: (sum(result[0].values()), sum(result[1].values())))

    def run_full_image_workflow_for_addon(self, content_folder: str, step_offset: int=0, total_steps: int=7, excluded_steps: set[str] | None=None):
        excluded_steps = excluded_steps or set()
        dds_size = 0
        dds_count = 0
        img_size = 0
        img_count = 0
        dxt_size = 0
        dxt_count = 0
        vtf_clamp_size = 0
        vtf_clamp_count = 0
        mipmap_size = 0
        mipmap_count = 0
        vtf_resave_count = 0
        png_size = 0
        png_count = 0
        step_number = step_offset
        if 'dds_to_png' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Converting DDS files to PNG...')
            dds_size, dds_count = convert_dds_to_png(content_folder, delete_originals=True, progress_callback=self.worker.progress.emit)
            print(f'Converted {dds_count} DDS files, saving {format_size(dds_size)}')
        if 'images_to_png' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Converting images to PNG...')
            img_size, img_count = convert_images_to_png(content_folder, progress_callback=self.worker.progress.emit)
            print(f'Converted {img_count} image files, saving {format_size(img_size)}')
        if 'vtf_to_dxt' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Converting VTF files to DXT...')
            dxt_size, dxt_count = resize_and_compress(content_folder, 1000000, progress_callback=self.worker.progress.emit)
            print(f'Changed {dxt_count} VTF files, saving {format_size(dxt_size)}')
        if 'clamp_vtf' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Clamping VTF file sizes to 1024px...')
            vtf_clamp_size, vtf_clamp_count = resize_and_compress(content_folder, 1024, progress_callback=self.worker.progress.emit)
            print(f'Changed {vtf_clamp_count} VTF files, saving {format_size(vtf_clamp_size)}')
        if 'remove_mipmaps' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Removing mipmaps...')
            mipmap_size, mipmap_count = remove_mipmaps(content_folder, progress_callback=self.worker.progress.emit)
            print(f'Removed mipmaps from {mipmap_count} VTF files, saving {format_size(mipmap_size)}')
        if 'resave_vtf' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Resaving VTF files (autorefresh)...')
            vtf_resave_count = self.resave_vtf_files(content_folder)
            print(f'Resaved {vtf_resave_count} VTF files.')
        if 'clamp_png' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Clamping PNG file sizes to 512px...')
            png_size, png_count = clamp_pngs(content_folder, 512, progress_callback=self.worker.progress.emit)
            print(f'Processed {png_count} PNG files, saving {format_size(png_size)}')
        if step_number > step_offset:
            print('\nFull image workflow completed successfully.')
        return ({'dds_size': dds_size, 'img_size': img_size, 'dxt_size': dxt_size, 'vtf_clamp_size': vtf_clamp_size, 'mipmap_size': mipmap_size, 'png_size': png_size}, {'dds_count': dds_count, 'img_count': img_count, 'dxt_count': dxt_count, 'vtf_clamp_count': vtf_clamp_count, 'mipmap_count': mipmap_count, 'vtf_resave_count': vtf_resave_count, 'png_count': png_count})

    def run_full_sound_workflow_task(self, content_folder: str, step_offset: int=0, total_steps: int=3):
        if self.is_addon_content_folder(content_folder):
            return self.run_full_sound_workflow_for_addon(content_folder, step_offset=step_offset, total_steps=total_steps)
        return self.run_content_targets(content_folder, 'Full sound workflow', lambda addon_path, *_args: self.run_full_sound_workflow_for_addon(addon_path, step_offset=step_offset, total_steps=total_steps), result_mapper=lambda result: (sum(result[0].values()), sum(result[1].values())))

    def run_full_sound_workflow_for_addon(self, content_folder: str, step_offset: int=0, total_steps: int=3, excluded_steps: set[str] | None=None):
        excluded_steps = excluded_steps or set()
        ogg_size = 0
        ogg_count = 0
        resample_size = 0
        resample_count = 0
        metadata_size = 0
        metadata_count = 0
        step_number = step_offset
        if 'sounds_to_ogg' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Converting sound files to OGG...')
            ogg_size, ogg_count = sounds_to_ogg(content_folder, progress_callback=self.worker.progress.emit)
            print(f'Converted {ogg_count} sound files, saving {format_size(ogg_size)}')
        if 'resample_oggs' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Resampling unsupported OGG sample rates...')
            resample_size, resample_count = resample_oggs(content_folder, target_rate=44100, progress_callback=self.worker.progress.emit)
            print(f'Resampled {resample_count} OGG files, saving {format_size(resample_size)}')
        if 'strip_audio_metadata' not in excluded_steps:
            step_number += 1
            print(f'\n[{step_number}/{total_steps}] Stripping audio metadata...')
            metadata_size, metadata_count = strip_audio_metadata(content_folder, progress_callback=self.worker.progress.emit)
            print(f'Stripped metadata from {metadata_count} audio files, saving {format_size(metadata_size)}')
        if step_number > step_offset:
            print('\nFull sound workflow completed successfully.')
        return ({'ogg_size': ogg_size, 'resample_size': resample_size, 'metadata_size': metadata_size}, {'ogg_count': ogg_count, 'resample_count': resample_count, 'metadata_count': metadata_count})

    def resave_vtf_files(self, content_folder: str) -> int:
        vtf_resave_count = 0
        for root, _, files in os.walk(content_folder):
            for filename in files:
                if filename.lower().endswith('.vtf'):
                    file_path = os.path.join(root, filename)
                    try:
                        with open(file_path, 'r+b') as f:
                            data = f.read()
                            f.seek(0)
                            f.write(data)
                            f.truncate()
                        vtf_resave_count += 1
                    except Exception as e:
                        print(f'Failed to resave {file_path}: {e}')
        return vtf_resave_count

def _ffmpeg_available() -> bool:
    return ffmpeg_present() or bool(shutil.which('ffmpeg'))

def _ensure_ffmpeg_for_action(parent, action_name: str) -> bool:
    """Ask before downloading ffmpeg for an action that requires it."""
    if _ffmpeg_available():
        return True
    prompt = f'"{action_name}" needs ffmpeg.\n\nffmpeg is a command-line tool used to convert, re-encode, and process audio files.\nThis app uses it for audio-related actions.\n\nDo you want to download ffmpeg now?'
    if QtWidgets.QMessageBox.question(parent, 'Download ffmpeg?', prompt, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
        return False
    progress = QtWidgets.QProgressDialog('Downloading ffmpeg...', None, 0, 100, parent)
    progress.setWindowTitle('Downloading ffmpeg')
    progress.setWindowModality(QtCore.Qt.ApplicationModal)
    progress.setMinimumWidth(420)
    progress.setCancelButton(None)
    progress.show()
    QtWidgets.QApplication.processEvents()
    result = [False]

    def on_progress(downloaded, total):
        pct = int(downloaded * 100 / total)
        mb_done = downloaded / 1048576
        mb_total = total / 1048576
        progress.setValue(pct)
        progress.setLabelText(f'Downloading ffmpeg... {mb_done:.1f} / {mb_total:.1f} MB')
        QtWidgets.QApplication.processEvents()

    class _DownloadWorker(QtCore.QObject):
        finished = QtCore.Signal(bool)

        @QtCore.Slot()
        def run(self):
            ok = download_ffmpeg(progress_callback=on_progress)
            self.finished.emit(ok)
    thread = QtCore.QThread()
    worker = _DownloadWorker()
    worker.moveToThread(thread)
    loop = QtCore.QEventLoop()

    def on_finished(ok):
        result[0] = ok
        thread.quit()

    def on_thread_finished():
        loop.quit()
    worker.finished.connect(on_finished)
    thread.started.connect(worker.run)
    thread.finished.connect(on_thread_finished)
    thread.start()
    loop.exec()
    progress.close()
    if not result[0]:
        QtWidgets.QMessageBox.warning(parent, 'ffmpeg not available', 'Could not download ffmpeg automatically.\nAudio features will not work until ffmpeg.exe is placed in the project root.\nGet it from https://ffmpeg.org/download.html')
        return False
    return True

def _ensure_ffmpeg():
    """Download ffmpeg on first run, showing a progress dialog."""
    if ffmpeg_present():
        return
    progress = QtWidgets.QProgressDialog('Downloading ffmpeg (first run only)…', None, 0, 100)
    progress.setWindowTitle('Downloading ffmpeg')
    progress.setWindowModality(QtCore.Qt.ApplicationModal)
    progress.setMinimumWidth(420)
    progress.setCancelButton(None)
    progress.show()
    QtWidgets.QApplication.processEvents()
    result = [False]

    def on_progress(downloaded, total):
        pct = int(downloaded * 100 / total)
        mb_done = downloaded / 1048576
        mb_total = total / 1048576
        progress.setValue(pct)
        progress.setLabelText(f'Downloading ffmpeg… {mb_done:.1f} / {mb_total:.1f} MB')
        QtWidgets.QApplication.processEvents()

    class _DownloadWorker(QtCore.QObject):
        finished = QtCore.Signal(bool)

        @QtCore.Slot()
        def run(self):
            ok = download_ffmpeg(progress_callback=on_progress)
            self.finished.emit(ok)
    thread = QtCore.QThread()
    worker = _DownloadWorker()
    worker.moveToThread(thread)
    loop = QtCore.QEventLoop()

    def on_finished(ok):
        result[0] = ok
        thread.quit()

    def on_thread_finished():
        loop.quit()
    worker.finished.connect(on_finished)
    thread.started.connect(worker.run)
    thread.finished.connect(on_thread_finished)
    thread.start()
    loop.exec()
    progress.close()
    if not result[0]:
        QtWidgets.QMessageBox.warning(None, 'ffmpeg not available', 'Could not download ffmpeg automatically.\nAudio features will not work until ffmpeg.exe is placed in the project root.\nGet it from https://ffmpeg.org/download.html')

def main():
    if sys.platform == 'win32':
        import ctypes
        myappid = 'cfcservers.gmaddonoptimization.tools.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
if __name__ == '__main__':
    main()
