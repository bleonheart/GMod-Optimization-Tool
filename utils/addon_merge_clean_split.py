import json
import logging
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from srctools.filesys import FileSystemChain, RawFileSystem, get_filesystem
from srctools.mdl import Model
from srctools.vmt import Material
ROOT = Path('C:\\\\Users\\\\David\\\\Desktop\\\\backup')
MERGE_SOURCE = Path('E:\\\\original')
GMOD_DIR = Path('D:\\\\SteamLibrary\\\\steamapps\\\\common\\\\GarrysMod\\\\garrysmod')
LUA_DIR = Path('E:\\\\GMOD\\\\Server\\\\garrysmod\\\\gamemodes\\\\metrorp\\\\devmodules\\\\bonemerge')
LOG_FILE = Path.home() / 'Desktop' / 'found_log.txt'
WORKSHOP_FILE = Path.home() / 'Desktop' / 'workshop_mdls.txt'
MATERIALS_FILE = Path.home() / 'Desktop' / 'materials_list.txt'
JSON_FILE = Path.home() / 'Desktop' / 'cdmaterials.json'
SOUND_EXTS = {'.wav', '.mp3', '.ogg', '.flac', '.aac'}
PARTICLE_EXTS = {'.pcf'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.tga', '.dds', '.bmp', '.gif'}
MATERIAL_EXTS = {'.vmt', '.vtf'}
MODEL_EXTS = {'.mdl', '.phy', '.vvd', '.vtx', '.dx90.vtx'}
CORE_DIRS = {'lua', 'materials', 'models', 'sound', 'maps', 'particles', 'scripts', 'resource', 'cfg', 'gamemodes', 'shaders'}
GB = 1024 ** 3

def _n(p):
    return p.replace('\\', '/').lower()

def merge(s, d, progress_callback=None):
    """Merge addon folders from source to destination.

    Args:
        s: Source path (Path or str)
        d: Destination path (Path or str)
        progress_callback: Optional callback function for progress updates
    """
    s = Path(s)
    d = Path(d)
    total_files = sum((len(list(a.rglob('*'))) for a in s.iterdir() if a.is_dir()))
    processed_files = 0
    for a in s.iterdir():
        if not a.is_dir():
            continue
        for f in a.rglob('*'):
            if not f.is_file():
                continue
            t = d / f.relative_to(a)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
            processed_files += 1
            if progress_callback and processed_files % 10 == 0:
                progress_callback(processed_files, total_files)
    if progress_callback:
        progress_callback(total_files, total_files)

def _find_content_root(pack_folder):
    """Find the most likely content root inside a content pack folder."""
    pack_folder = Path(pack_folder)
    if not pack_folder.exists() or not pack_folder.is_dir():
        return None
    root_dirs = {p.name.lower() for p in pack_folder.iterdir() if p.is_dir()}
    if root_dirs & CORE_DIRS:
        return pack_folder
    candidates = []
    for current_root, dirnames, _ in os.walk(pack_folder):
        current_path = Path(current_root)
        dir_set = {d.lower() for d in dirnames}
        matches = dir_set & CORE_DIRS
        if matches:
            depth = len(current_path.relative_to(pack_folder).parts)
            candidates.append((depth, -len(matches), current_path))
    if not candidates:
        return pack_folder
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2]).lower()))
    return candidates[0][2]

def extract_content_packs(source, destination, progress_callback=None):
    """Extract a folder of content packs into one content folder, normalizing wrapper directories."""
    source = Path(source)
    destination = Path(destination)
    if not source.exists() or not source.is_dir():
        raise ValueError(f'Source directory {source} does not exist or is not a directory')
    destination.mkdir(parents=True, exist_ok=True)
    pack_folders = [f for f in source.iterdir() if f.is_dir()]
    if not pack_folders:
        print('No content pack folders found to extract')
        return (0, 0)
    files_to_copy = []
    pack_summaries = []
    for pack_folder in pack_folders:
        content_root = _find_content_root(pack_folder)
        if content_root is None:
            continue
        root_name = 'pack root' if content_root == pack_folder else str(content_root.relative_to(pack_folder))
        pack_file_count = 0
        for file_path in content_root.rglob('*'):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(content_root)
            if not rel_path.parts:
                continue
            top_level = rel_path.parts[0].lower()
            if top_level not in CORE_DIRS:
                continue
            files_to_copy.append((file_path, destination / rel_path))
            pack_file_count += 1
        pack_summaries.append((pack_folder.name, root_name, pack_file_count))
    total_files = len(files_to_copy)
    if total_files == 0:
        print('No content files found inside the selected content packs')
        return (0, 0)
    print('')
    print('Starting Content Pack Extraction...')
    print(f'Source: {source}')
    print(f'Destination: {destination}')
    print(f'Found {len(pack_folders)} content pack folders')
    for pack_name, root_name, pack_file_count in pack_summaries:
        print(f"  - {pack_name}: using '{root_name}' ({pack_file_count} files)")
    copied_files = 0
    overwritten_files = 0
    for idx, (file_path, target_path) in enumerate(files_to_copy, 1):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            overwritten_files += 1
        shutil.copy2(file_path, target_path)
        copied_files += 1
        if progress_callback and (idx % 10 == 0 or idx == total_files):
            progress_callback(idx, total_files)
    print('')
    print('Content Pack Extraction Summary:')
    print(f'Files copied: {copied_files}')
    print(f'Files overwritten: {overwritten_files}')
    print(f'Pack folders processed: {len(pack_folders)}')
    return (copied_files, total_files)

def merge_and_remove_legacy(source, destination, progress_callback=None):
    """Merge addon folders from source to destination and remove the original addon folders.

    Args:
        source: Source path containing addon folders (Path or str)
        destination: Destination path (Path or str)
        progress_callback: Optional callback function for progress updates
    """
    source = Path(source)
    destination = Path(destination)
    if not source.exists() or not source.is_dir():
        raise ValueError(f'Source directory {source} does not exist or is not a directory')
    print('')
    print('Starting Merge Operation...')
    print(f'Source: {source}')
    print(f'Destination: {destination}')
    addon_folders = [f for f in source.iterdir() if f.is_dir()]
    if not addon_folders:
        print('No addon folders found to merge')
        return
    total_files = sum((len(list(a.rglob('*'))) for a in addon_folders if a.is_dir()))
    processed_files = 0
    files_moved = 0
    duplicates = 0
    space_saved = 0
    print(f'Found {len(addon_folders)} addon folders to merge')
    for addon_folder in addon_folders:
        print(f'Processing folder: {addon_folder.name}')
        for f in addon_folder.rglob('*'):
            if not f.is_file():
                continue
            rel_path = f.relative_to(addon_folder)
            target = destination / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                duplicates += 1
                space_saved += f.stat().st_size
                f.unlink()
            else:
                shutil.copy2(f, target)
                files_moved += 1
            processed_files += 1
            if progress_callback and processed_files % 10 == 0:
                progress_callback(processed_files, total_files)
    if progress_callback:
        progress_callback(total_files, total_files)
    print('')
    print('Merge Operation Summary:')
    print(f'Files moved: {files_moved}')
    print(f'Duplicates found: {duplicates}')
    print(f'Space saved from duplicates: {space_saved / 1024:.2f} KB')
    print('')
    print('Removing original addon folders...')
    for addon_folder in addon_folders:
        try:
            shutil.rmtree(addon_folder)
            print(f'Removed folder: {addon_folder.name}')
        except Exception as e:
            print(f'Warning: Could not remove {addon_folder.name}: {e}')
    print('')
    print(f'Successfully merged and removed {len(addon_folders)} addon folders')

def _iter_top_level_addon_folders(source: Path):
    return [folder for folder in source.iterdir() if folder.is_dir()]

def _collect_files_for_merge(addon_folders):
    files_by_folder = {}
    for addon_folder in addon_folders:
        files_by_folder[addon_folder] = [file_path for file_path in addon_folder.rglob('*') if file_path.is_file()]
    return files_by_folder

def _collect_split_candidates(destination: Path):
    files = []
    for file_path in destination.rglob('*'):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(destination)
        if rel_path.parts and rel_path.parts[0].isdigit():
            continue
        try:
            file_size = file_path.stat().st_size
        except OSError:
            continue
        files.append((file_path, file_size, rel_path))
    files.sort(key=lambda item: str(item[2]).lower())
    return files

def merge_addon_workflow(source, destination, pack_size_gb=3.9, remove_source_addon_folders=False, merge_only=False, remove_pre_split_files=False, progress_callback=None):
    """Merge addon folders, then optionally split the merged result into numbered packs.

    This mirrors the reference Collection-Optimizer flow:
    1. Merge every top-level addon folder into the destination root.
    2. Optionally split the merged root into numbered packs inside that same destination.
    3. Optionally delete the source addon folders and/or the pre-split merged files.
    """
    source = Path(source)
    destination = Path(destination)
    if not source.exists() or not source.is_dir():
        raise ValueError(f'Source directory {source} does not exist or is not a directory')
    destination.mkdir(parents=True, exist_ok=True)
    addon_folders = _iter_top_level_addon_folders(source)
    if not addon_folders:
        print('No addon folders found to merge')
        return
    print('')
    print('Starting Addon Merge Workflow...')
    print(f'Source: {source}')
    print(f'Destination: {destination}')
    print(f'Pack size: {pack_size_gb:.2f} GB')
    print(f"Merge only: {('Yes' if merge_only else 'No')}")
    print(f"Remove source addon folders: {('Yes' if remove_source_addon_folders else 'No')}")
    print(f"Remove pre-split files: {('Yes' if remove_pre_split_files else 'No')}")
    merge_files = _collect_files_for_merge(addon_folders)
    merge_file_count = sum((len(files) for files in merge_files.values()))
    total_operations = merge_file_count
    processed_operations = 0
    files_copied = 0
    overwritten_files = 0
    print('')
    print(f'Merging {len(addon_folders)} addon folders into the destination root...')
    for addon_folder in addon_folders:
        print(f'Processing folder: {addon_folder.name}')
        for file_path in merge_files[addon_folder]:
            rel_path = file_path.relative_to(addon_folder)
            target = destination / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                overwritten_files += 1
            shutil.copy2(file_path, target)
            files_copied += 1
            processed_operations += 1
            if progress_callback and (processed_operations % 10 == 0 or processed_operations == total_operations):
                progress_callback(processed_operations, total_operations)
    if merge_only:
        print('')
        print('Merge summary:')
        print(f'Files copied: {files_copied}')
        print(f'Existing files overwritten: {overwritten_files}')
        if remove_source_addon_folders:
            print('')
            print('Removing source addon folders...')
            for addon_folder in addon_folders:
                try:
                    shutil.rmtree(addon_folder)
                    print(f'Removed folder: {addon_folder.name}')
                except Exception as e:
                    print(f'Warning: Could not remove {addon_folder.name}: {e}')
        print('')
        print('Addon merge workflow complete.')
        return
    split_candidates = _collect_split_candidates(destination)
    total_operations += len(split_candidates)
    if not split_candidates:
        print('')
        print('No merged files were found to split.')
    else:
        print('')
        print(f'Starting Split Operation on: {destination}')
        max_pack_size_bytes = int(pack_size_gb * GB)
        current_pack = 1
        current_pack_size = 0
        created_pack_numbers = set()
        for file_path, file_size, rel_path in split_candidates:
            if current_pack_size + file_size > max_pack_size_bytes and current_pack_size > 0:
                current_pack += 1
                current_pack_size = 0
            pack_root = destination / str(current_pack)
            split_target = pack_root / rel_path
            split_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, split_target)
            current_pack_size += file_size
            created_pack_numbers.add(current_pack)
            processed_operations += 1
            if progress_callback and (processed_operations % 10 == 0 or processed_operations == total_operations):
                progress_callback(processed_operations, total_operations)
        print('Splitting complete. Packs have been created under the destination folder.')
        print('Pack sizes:')
        for pack_number in sorted(created_pack_numbers):
            pack_dir = destination / str(pack_number)
            pack_size = sum((f.stat().st_size for f in pack_dir.rglob('*') if f.is_file()))
            print(f'  Pack {pack_number}: {pack_size / GB:.2f} GB')
        if remove_pre_split_files:
            print('')
            print('Removing pre-split files from the destination root...')
            removed_files = 0
            removed_bytes = 0
            for file_path, _, _ in split_candidates:
                try:
                    removed_bytes += file_path.stat().st_size
                except OSError:
                    pass
                try:
                    file_path.unlink()
                    removed_files += 1
                except Exception as e:
                    print(f'Warning: Could not remove {file_path}: {e}')
            print(f'Removed {removed_files} pre-split files ({removed_bytes / GB:.2f} GB)')
    if remove_source_addon_folders:
        print('')
        print('Removing source addon folders...')
        for addon_folder in addon_folders:
            try:
                shutil.rmtree(addon_folder)
                print(f'Removed folder: {addon_folder.name}')
            except Exception as e:
                print(f'Warning: Could not remove {addon_folder.name}: {e}')
    if progress_callback and total_operations == 0:
        progress_callback(0, 1)
    elif progress_callback:
        progress_callback(total_operations, total_operations)
    print('')
    print('Addon merge workflow summary:')
    print(f'Files copied into destination root: {files_copied}')
    print(f'Existing files overwritten during merge: {overwritten_files}')
    print('Addon merge workflow complete.')

def merge_and_split(source, destination, chunk_size_gb=3.9, progress_callback=None):
    """Merge addon folders and split the result into chunks of specified size.

    Args:
        source: Source path containing addon folders (Path or str)
        destination: Destination path for the chunked folders (Path or str)
        chunk_size_gb: Size of each chunk in GB (default 3.90)
        progress_callback: Optional callback function for progress updates
    """
    source = Path(source)
    destination = Path(destination)
    chunk_size_bytes = int(chunk_size_gb * GB)
    print('')
    print('Starting Merge Operation...')
    print(f'Source: {source}')
    print(f'Destination: {destination}')
    addon_folders = [f for f in source.iterdir() if f.is_dir()]
    if not addon_folders:
        print('No addon folders found to merge')
        return
    print(f'Found {len(addon_folders)} addon folders to merge and split')
    all_files = []
    for addon_folder in addon_folders:
        print(f'Processing folder: {addon_folder.name}')
        for f in addon_folder.rglob('*'):
            if f.is_file():
                try:
                    size = f.stat().st_size
                    all_files.append((f, size, f.relative_to(addon_folder)))
                except OSError:
                    continue
    all_files.sort(key=lambda x: x[1], reverse=True)
    print(f'Total files to process: {len(all_files)}')
    chunks = []
    current_chunk = []
    current_size = 0
    chunk_num = 1
    for file_path, file_size, rel_path in all_files:
        if current_size + file_size > chunk_size_bytes and current_chunk:
            chunks.append((chunk_num, current_chunk.copy()))
            chunk_num += 1
            current_chunk = []
            current_size = 0
        current_chunk.append((file_path, rel_path))
        current_size += file_size
    if current_chunk:
        chunks.append((chunk_num, current_chunk))
    print(f'Created {len(chunks)} chunks')
    print('')
    print(f'Starting Split Operation on: {destination}')
    total_files = len(all_files)
    processed_files = 0
    for chunk_num, files in chunks:
        chunk_dir = destination / str(chunk_num)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        print(f'Creating pack {chunk_num} with {len(files)} files')
        for file_path, rel_path in files:
            target = chunk_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(file_path, target)
                processed_files += 1
                if progress_callback and processed_files % 10 == 0:
                    progress_callback(processed_files, total_files)
            except Exception as e:
                print(f'Warning: Could not copy {file_path} to {target}: {e}')
    if progress_callback:
        progress_callback(total_files, total_files)
    print('')
    print('Pack sizes:')
    for chunk_num in range(1, len(chunks) + 1):
        chunk_dir = destination / str(chunk_num)
        if chunk_dir.exists():
            chunk_size = sum((f.stat().st_size for f in chunk_dir.rglob('*') if f.is_file()))
            print(f'  Pack {chunk_num}: {chunk_size / GB:.2f} GB')
    print('')
    print(f"Splitting complete. Packs have been created under '{destination}'.")
    print(f'Successfully merged and split into {len(chunks)} packs of approximately {chunk_size_gb}GB each')

def merge_split_and_remove_legacy(source, destination, chunk_size_gb=3.9, progress_callback=None):
    """Merge addon folders, split the result into chunks, and remove the original addon folders.

    Args:
        source: Source path containing addon folders (Path or str)
        destination: Destination path for the chunked folders (Path or str)
        chunk_size_gb: Size of each chunk in GB (default 3.90)
        progress_callback: Optional callback function for progress updates
    """
    source = Path(source)
    destination = Path(destination)
    chunk_size_bytes = int(chunk_size_gb * GB)
    print('')
    print('Starting Merge, Split, and Remove Legacy Operation...')
    print(f'Source: {source}')
    print(f'Destination: {destination}')
    addon_folders = [f for f in source.iterdir() if f.is_dir()]
    if not addon_folders:
        print('No addon folders found to merge')
        return
    print(f'Found {len(addon_folders)} addon folders to merge, split, and remove')
    all_files = []
    for addon_folder in addon_folders:
        print(f'Processing folder: {addon_folder.name}')
        for f in addon_folder.rglob('*'):
            if f.is_file():
                try:
                    size = f.stat().st_size
                    all_files.append((f, size, f.relative_to(addon_folder)))
                except OSError:
                    continue
    all_files.sort(key=lambda x: x[1], reverse=True)
    print(f'Total files to process: {len(all_files)}')
    chunks = []
    current_chunk = []
    current_size = 0
    chunk_num = 1
    for file_path, file_size, rel_path in all_files:
        if current_size + file_size > chunk_size_bytes and current_chunk:
            chunks.append((chunk_num, current_chunk.copy()))
            chunk_num += 1
            current_chunk = []
            current_size = 0
        current_chunk.append((file_path, rel_path))
        current_size += file_size
    if current_chunk:
        chunks.append((chunk_num, current_chunk))
    print(f'Created {len(chunks)} chunks')
    print('')
    print(f'Starting Split Operation on: {destination}')
    total_files = len(all_files)
    processed_files = 0
    for chunk_num, files in chunks:
        chunk_dir = destination / str(chunk_num)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        print(f'Creating pack {chunk_num} with {len(files)} files')
        for file_path, rel_path in files:
            target = chunk_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(file_path, target)
                processed_files += 1
                if progress_callback and processed_files % 10 == 0:
                    progress_callback(processed_files, total_files)
            except Exception as e:
                print(f'Warning: Could not copy {file_path} to {target}: {e}')
    if progress_callback:
        progress_callback(total_files, total_files)
    print('')
    print('Pack sizes:')
    for chunk_num in range(1, len(chunks) + 1):
        chunk_dir = destination / str(chunk_num)
        if chunk_dir.exists():
            chunk_size = sum((f.stat().st_size for f in chunk_dir.rglob('*') if f.is_file()))
            print(f'  Pack {chunk_num}: {chunk_size / GB:.2f} GB')
    print('')
    print(f"Splitting complete. Packs have been created under '{destination}'.")
    print('')
    print('Removing original addon folders...')
    for addon_folder in addon_folders:
        try:
            shutil.rmtree(addon_folder)
            print(f'Removed folder: {addon_folder.name}')
        except Exception as e:
            print(f'Warning: Could not remove {addon_folder.name}: {e}')
    print('')
    print(f'Successfully merged, split into {len(chunks)} packs, and removed {len(addon_folders)} legacy addon folders')

def flatten(r):
    for s in r.iterdir():
        if not s.is_dir() or s.name.lower() in CORE_DIRS:
            continue
        for f in s.rglob('*'):
            if not f.is_file():
                continue
            t = r / f.relative_to(s)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)

def read_lua():
    parts = []
    for p in LUA_DIR.rglob('*.lua'):
        try:
            parts.append(p.read_text('utf-8', 'ignore'))
        except:
            pass
    return _n('\n'.join(parts))

def gather():
    cats = defaultdict(list)
    me = sorted(MODEL_EXTS, key=lambda e: -len(e))
    for f in ROOT.rglob('*'):
        if not f.is_file():
            continue
        rel = _n(str(f.relative_to(ROOT)))
        n = f.name.lower()
        ext = next((e for e in me if n.endswith(e)), None)
        if ext:
            cats['model'].append((rel[:-len(ext)], f))
            continue
        ext = f.suffix.lower()
        if ext in SOUND_EXTS:
            cats['sound'].append((rel, f))
        elif ext in PARTICLE_EXTS:
            cats['particle'].append((rel, f))
        elif ext in IMAGE_EXTS:
            cats['image'].append((rel, f))
        elif ext in MATERIAL_EXTS:
            cats['material'].append((rel.rsplit('.', 1)[0], f))
    return cats

def extract_cdmaterials(fs, name):
    mdl = Model(fs, fs[name])
    return getattr(mdl, 'cdmaterials', [])

def _normalize_material_dir_path(material_dir):
    material_dir = _n(str(material_dir).replace('\\', '/')).strip('/')
    if not material_dir.startswith('materials/'):
        material_dir = f'materials/{material_dir}'
    return material_dir.rstrip('/')

def _normalize_material_file_path(material_path):
    material_path = _n(str(material_path).replace('\\', '/')).strip('/')
    if material_path.endswith('.vmt'):
        material_path = material_path[:-4]
    if material_path.startswith('materials/'):
        material_path = material_path[len('materials/'):]
    return material_path

def _material_file_exists(base_folder, material_path_no_ext):
    return (Path(base_folder) / 'materials' / f'{material_path_no_ext}.vmt').exists()

def _extract_related_vtf_paths(vmt_path):
    related = set()
    try:
        with open(vmt_path, 'r', encoding='utf-8', errors='ignore') as handle:
            material = Material.parse(handle, filename=str(vmt_path))
        for key, value in material.items():
            normalized_key = key.lower().lstrip('$')
            if normalized_key.endswith('texture') or normalized_key.endswith('map') or 'bump' in normalized_key:
                normalized_value = _n(str(value).strip().strip('"')).strip('/')
                if not normalized_value:
                    continue
                if normalized_value.startswith('materials/'):
                    normalized_value = normalized_value[len('materials/'):]
                if normalized_value.endswith('.vtf'):
                    normalized_value = normalized_value[:-4]
                related.add(f'materials/{normalized_value}.vtf')
    except Exception:
        try:
            text = Path(vmt_path).read_text('utf-8', errors='ignore')
        except Exception:
            return related
        for _, raw_value in re.findall('"\\$?([^"]+)"\\s+"([^"]+)"', text, flags=re.IGNORECASE):
            normalized_value = _n(raw_value).strip('/')
            if not normalized_value:
                continue
            if normalized_value.startswith('materials/'):
                normalized_value = normalized_value[len('materials/'):]
            if normalized_value.endswith('.vtf'):
                normalized_value = normalized_value[:-4]
            related.add(f'materials/{normalized_value}.vtf')
    return related

def _collect_model_materials_status(folder_path, gmod_dir=None, progress_callback=None):
    folder_path = Path(folder_path)
    if gmod_dir:
        gmod_dir = Path(gmod_dir)
    else:
        gmod_dir = GMOD_DIR if GMOD_DIR.exists() else None
    entries = []
    models_with_materials = 0
    total_materials = 0
    mdl_files = []
    for root, _, files in os.walk(str(folder_path)):
        for fn in files:
            if fn.lower().endswith('.mdl'):
                mdl_files.append((Path(root), fn))
    total_models = len(mdl_files)
    material_status = {}
    texture_status = {}
    for idx, (base, fn) in enumerate(mdl_files):
        if progress_callback:
            progress_callback(idx + 1, total_models)
        model_path = base / fn
        rel_path = model_path.relative_to(folder_path)
        if gmod_dir and gmod_dir.exists():
            fs = FileSystemChain(RawFileSystem(str(base)), get_filesystem(str(gmod_dir)))
        else:
            fs = RawFileSystem(str(base))
        try:
            model = Model(fs, fs[fn])
            mats = extract_cdmaterials(fs, fn)
            textures = []
            try:
                textures = [_normalize_material_file_path(tex) for tex in model.iter_textures()]
            except Exception:
                textures = []
            skin_texture_names: list[str] = []
            try:
                skins = getattr(model, 'skins', None)
                if skins:
                    seen: set[str] = set()
                    for group in skins:
                        for name in group:
                            if name and name not in seen:
                                seen.add(name)
                                skin_texture_names.append(name)
            except Exception:
                pass
            check_locations = [folder_path]
            if gmod_dir and gmod_dir.exists():
                check_locations.append(gmod_dir)
            material_info = []
            texture_info = []
            if mats:
                models_with_materials += 1
                total_materials += len(mats)
                for mat_dir in mats:
                    mat_path = _normalize_material_dir_path(mat_dir)
                    found = False
                    try:
                        for check_base in check_locations:
                            actual_path = check_base / mat_path
                            if actual_path.exists() and actual_path.is_dir():
                                try:
                                    if any(actual_path.iterdir()):
                                        found = True
                                        break
                                except:
                                    pass
                    except:
                        found = False
                    expected_vmts: dict[str, bool] = {}
                    for tex_name in skin_texture_names:
                        vmt_rel = f'{mat_path}/{_n(tex_name)}.vmt'
                        vmt_found = any(((cb / vmt_rel).exists() for cb in check_locations))
                        expected_vmts[vmt_rel] = vmt_found
                    if expected_vmts and (not any(expected_vmts.values())):
                        found = False
                    material_info.append({'dir': mat_dir, 'found': found, 'expected_vmts': expected_vmts})
                    if mat_dir not in material_status:
                        material_status[mat_dir] = {'found': found, 'models': [], 'expected_vmts': {}}
                    material_status[mat_dir]['models'].append(str(rel_path))
                    if found:
                        material_status[mat_dir]['found'] = True
                    for vmt_rel, vmt_found in expected_vmts.items():
                        existing = material_status[mat_dir]['expected_vmts'].get(vmt_rel, False)
                        material_status[mat_dir]['expected_vmts'][vmt_rel] = existing or vmt_found
            for texture_path in textures:
                found = False
                for check_base in check_locations:
                    if check_base and _material_file_exists(check_base, texture_path):
                        found = True
                        break
                texture_info.append({'path': texture_path, 'found': found})
                if texture_path not in texture_status:
                    texture_status[texture_path] = {'found': found, 'models': []}
                texture_status[texture_path]['models'].append(str(rel_path))
                if found:
                    texture_status[texture_path]['found'] = True
            entries.append({'model': str(rel_path), 'full_path': str(model_path), 'materials': mats, 'material_info': material_info, 'textures': textures, 'texture_info': texture_info})
        except Exception as e:
            entries.append({'model': str(rel_path), 'full_path': str(model_path), 'materials': [], 'material_info': [], 'textures': [], 'texture_info': [], 'error': str(e)})
    found_materials = set()
    not_found_materials = set()
    for mat_dir, status in material_status.items():
        if status['found']:
            found_materials.add(mat_dir)
        else:
            not_found_materials.add(mat_dir)
    found_texture_files = set()
    missing_texture_files = set()
    for texture_path, status in texture_status.items():
        if status['found']:
            found_texture_files.add(texture_path)
        else:
            missing_texture_files.add(texture_path)
    return {'folder_path': folder_path, 'gmod_dir': gmod_dir, 'entries': entries, 'total_models': total_models, 'models_with_materials': models_with_materials, 'total_materials': total_materials, 'material_status': material_status, 'texture_status': texture_status, 'found_materials': found_materials, 'not_found_materials': not_found_materials, 'found_texture_files': found_texture_files, 'missing_texture_files': missing_texture_files}

def extract_model_materials_to_markdown(folder_path, output_path, gmod_dir=None, progress_callback=None):
    """Extract materials from all models in a folder and write to a markdown file.
    
    Args:
        folder_path: Path to folder containing models
        output_path: Path to output markdown file
        gmod_dir: Optional path to Garry's Mod directory for fallback resources
        progress_callback: Optional callback function(current, total) for progress updates
    
    Returns:
        tuple: (total_models, models_with_materials, total_materials, found_materials, not_found_materials)
    """
    output_path = Path(output_path)
    report = _collect_model_materials_status(folder_path, gmod_dir=gmod_dir, progress_callback=progress_callback)
    folder_path = report['folder_path']
    entries = report['entries']
    total_models = report['total_models']
    models_with_materials = report['models_with_materials']
    total_materials = report['total_materials']
    material_status = report['material_status']
    found_materials = report['found_materials']
    not_found_materials = report['not_found_materials']
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('# Model Materials Extraction Report\n\n')
        f.write(f'**Source Folder:** `{folder_path}`\n\n')
        f.write(f'**Total Models Found:** {total_models}\n')
        f.write(f'**Models with Materials:** {models_with_materials}\n')
        f.write(f'**Total Material Directories:** {total_materials}\n')
        f.write(f'**Materials Found:** {len(found_materials)}\n')
        f.write(f'**Materials Not Found:** {len(not_found_materials)}\n\n')
        f.write('---\n\n')
        if not entries:
            f.write('No models found in the specified folder.\n')
        else:
            if found_materials or not_found_materials:
                f.write('## Materials Status Summary\n\n')
                if found_materials:
                    f.write('### ✅ Materials Found\n\n')
                    for mat_dir in sorted(found_materials):
                        status = material_status[mat_dir]
                        models = status['models']
                        f.write(f'- `{mat_dir}` (used by {len(set(models))} model(s))\n')
                        expected_vmts = status.get('expected_vmts', {})
                        present_vmts = sorted((p for p, found in expected_vmts.items() if found))
                        missing_vmts = sorted((p for p, found in expected_vmts.items() if not found))
                        for p in present_vmts:
                            f.write(f'  - ✅ `{p}`\n')
                        for p in missing_vmts:
                            f.write(f'  - ❌ `{p}`\n')
                    f.write('\n')
                if not_found_materials:
                    f.write('### ❌ Materials Not Found\n\n')
                    for mat_dir in sorted(not_found_materials):
                        status = material_status[mat_dir]
                        models = status['models']
                        f.write(f'- `{mat_dir}` (used by {len(set(models))} model(s))\n')
                        expected_vmts = status.get('expected_vmts', {})
                        missing_vmts = sorted((p for p, found in expected_vmts.items() if not found))
                        present_vmts = sorted((p for p, found in expected_vmts.items() if found))
                        for p in missing_vmts:
                            f.write(f'  - ❌ `{p}`\n')
                        for p in present_vmts:
                            f.write(f'  - ⚠️ `{p}` *(present elsewhere)*\n')
                    f.write('\n')
                f.write('---\n\n')
            material_to_models = defaultdict(list)
            for entry in entries:
                if entry['materials']:
                    for mat_dir in entry['materials']:
                        material_to_models[mat_dir].append(entry['model'])
                else:
                    material_to_models['(no materials)'].append(entry['model'])
            f.write('## Materials Summary\n\n')
            for mat_dir, models in sorted(material_to_models.items()):
                if mat_dir == '(no materials)':
                    status_icon = '⚠️'
                elif mat_dir in found_materials:
                    status_icon = '✅'
                elif mat_dir in not_found_materials:
                    status_icon = '❌'
                else:
                    status_icon = '❓'
                f.write(f'### {status_icon} `{mat_dir}`\n\n')
                f.write(f'**Used by {len(models)} model(s):**\n\n')
                for model in sorted(set(models)):
                    f.write(f'- `{model}`\n')
                f.write('\n')
                if mat_dir in material_status:
                    expected_vmts = material_status[mat_dir].get('expected_vmts', {})
                    if expected_vmts:
                        missing_vmts = sorted((p for p, found in expected_vmts.items() if not found))
                        present_vmts = sorted((p for p, found in expected_vmts.items() if found))
                        if missing_vmts:
                            f.write('**Missing files:**\n\n')
                            for p in missing_vmts:
                                f.write(f'- `{p}`\n')
                            f.write('\n')
                        if present_vmts:
                            f.write('**Present files:**\n\n')
                            for p in present_vmts:
                                f.write(f'- `{p}`\n')
                            f.write('\n')
            f.write('---\n\n')
            f.write('## Detailed Model List\n\n')
            for entry in sorted(entries, key=lambda x: x['model']):
                f.write(f"### `{entry['model']}`\n\n")
                if 'error' in entry:
                    f.write(f"⚠️ **Error:** {entry['error']}\n\n")
                if entry.get('material_info'):
                    f.write('**Material Directories:**\n\n')
                    for mat_info in entry['material_info']:
                        status = '✅ Found' if mat_info['found'] else '❌ Not Found'
                        f.write(f"- `{mat_info['dir']}` - {status}\n")
                    f.write('\n')
                elif entry['materials']:
                    f.write('**Material Directories:**\n\n')
                    for mat_dir in entry['materials']:
                        status = '✅ Found' if mat_dir in found_materials else '❌ Not Found'
                        f.write(f'- `{mat_dir}` - {status}\n')
                    f.write('\n')
                else:
                    f.write('*(No materials found)*\n\n')
                f.write('\n')
    return (total_models, models_with_materials, total_materials, len(found_materials), len(not_found_materials))

def extract_missing_materials_to_markdown(folder_path, output_path, gmod_dir=None, progress_callback=None):
    """Extract missing material directories referenced by models and write a focused markdown report.

    Reports two categories:
    1. Missing cdmaterials directories (entire folder absent / empty).
    2. Models with individual missing texture files detected via iter_textures(), which
       catches cases where the cdmaterials directory exists but specific VMTs are absent.

    Args:
        folder_path: Path to folder containing models.
        output_path: Path to output markdown file.
        gmod_dir: Optional path to Garry's Mod directory for fallback resources.
        progress_callback: Optional callback function(current, total) for progress updates.
    """
    output_path = Path(output_path)
    report = _collect_model_materials_status(folder_path, gmod_dir=gmod_dir, progress_callback=progress_callback)
    folder_path = report['folder_path']
    entries = report['entries']
    total_models = report['total_models']
    models_with_materials = report['models_with_materials']
    total_materials = report['total_materials']
    material_status = report['material_status']
    not_found_materials = report['not_found_materials']
    models_with_missing_textures = []
    for entry in entries:
        if 'error' in entry:
            continue
        missing_tex = sorted((f"materials/{t['path']}.vmt" for t in entry.get('texture_info', []) if not t['found']))
        if missing_tex:
            models_with_missing_textures.append((entry['model'], missing_tex))
    models_with_missing_textures.sort(key=lambda x: x[0])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('# Missing Materials Report\n\n')
        f.write(f'**Source Folder:** `{folder_path}`\n\n')
        f.write(f'**Total Models Found:** {total_models}\n')
        f.write(f'**Models with Materials:** {models_with_materials}\n')
        f.write(f'**Total Material Directories:** {total_materials}\n')
        f.write(f'**Missing Material Directories:** {len(not_found_materials)}\n')
        f.write(f'**Models with Missing Texture Files:** {len(models_with_missing_textures)}\n\n')
        f.write('---\n\n')
        if not_found_materials:
            f.write('## Missing Material Directories\n\n')
            for mat_dir in sorted(not_found_materials):
                status = material_status[mat_dir]
                models = sorted(set(status['models']))
                f.write(f'### `{mat_dir}`\n\n')
                f.write(f'Used by {len(models)} model(s):\n\n')
                for model in models:
                    f.write(f'- `{model}`\n')
                f.write('\n')
                expected_vmts = status.get('expected_vmts', {})
                if expected_vmts:
                    missing_vmts = sorted((p for p, found in expected_vmts.items() if not found))
                    present_vmts = sorted((p for p, found in expected_vmts.items() if found))
                    if missing_vmts:
                        f.write('**Missing files:**\n\n')
                        for p in missing_vmts:
                            f.write(f'- `{p}`\n')
                        f.write('\n')
                    if present_vmts:
                        f.write('**Present elsewhere (different cdmaterials dir):**\n\n')
                        for p in present_vmts:
                            f.write(f'- `{p}`\n')
                        f.write('\n')
        if models_with_missing_textures:
            if not_found_materials:
                f.write('---\n\n')
            f.write('## Models With Missing Texture Files\n\n')
            f.write('These models have their cdmaterials directory present on disk but are\n')
            f.write("missing specific VMT files detected via the model's texture list.\n\n")
            for model_path, missing_tex in models_with_missing_textures:
                f.write(f'### `{model_path}`\n\n')
                for tex in missing_tex:
                    f.write(f'- `{tex}`\n')
                f.write('\n')
        if not not_found_materials and (not models_with_missing_textures):
            f.write('No missing materials were found.\n')
        errored_entries = [entry for entry in entries if 'error' in entry]
        if errored_entries:
            f.write('---\n\n')
            f.write('## Models With Read Errors\n\n')
            for entry in sorted(errored_entries, key=lambda x: x['model']):
                f.write(f"- `{entry['model']}`: {entry['error']}\n")
    return (total_models, models_with_materials, total_materials, len(not_found_materials))

def recover_missing_materials_from_content_packs(folder_path, search_root, output_path, gmod_dir=None, show_individual_files=False, progress_callback=None):
    """Recover missing model materials by searching content packs and copying matches into the content folder.

    Args:
        folder_path: Path to the content folder containing the models.
        search_root: Root folder containing content pack sub-folders to search.
        output_path: Path to write the recovery report markdown file.
        gmod_dir: Optional path to the Garry's Mod directory for fallback resources.
        show_individual_files: When True, the report includes an "Individual File Status"
            section that enumerates the actual .vmt/.vtf files found in each missing
            cdmaterials directory across the content packs, and notes which were
            successfully recovered and which are still absent after all copy passes.
        progress_callback: Optional callback function(current, total) for progress updates.
    """
    folder_path = Path(folder_path)
    search_root = Path(search_root)
    output_path = Path(output_path)
    if not folder_path.exists() or not folder_path.is_dir():
        raise ValueError(f'Content folder does not exist: {folder_path}')
    if not search_root.exists() or not search_root.is_dir():
        raise ValueError(f'Search root does not exist: {search_root}')
    pack_folders = [pack for pack in sorted(search_root.iterdir()) if pack.is_dir()]
    if not pack_folders:
        raise ValueError(f'No content pack folders found under: {search_root}')
    total_models = sum((1 for root, _, files in os.walk(folder_path) for filename in files if filename.lower().endswith('.mdl')))
    total_material_candidates = 0
    pack_roots = []
    for pack_folder in pack_folders:
        content_root = _find_content_root(pack_folder)
        if content_root is None or not content_root.exists():
            continue
        pack_roots.append((pack_folder, content_root))
        total_material_candidates += sum((1 for candidate in content_root.rglob('*') if candidate.is_file() and candidate.suffix.lower() in MATERIAL_EXTS and _n(str(candidate.relative_to(content_root))).startswith('materials/')))
    total_operations = max(total_models + total_material_candidates + 1, 1)
    processed_operations = 0

    def emit_progress(step=1):
        nonlocal processed_operations
        processed_operations = min(processed_operations + step, total_operations)
        if progress_callback:
            progress_callback(processed_operations, total_operations)
    if progress_callback:
        progress_callback(0, total_operations)
    report = _collect_model_materials_status(folder_path, gmod_dir=gmod_dir, progress_callback=lambda current, total: progress_callback(current, total_operations) if progress_callback else None)
    processed_operations = max(processed_operations, total_models)
    missing_materials = sorted(report['missing_texture_files'])
    missing_dirs = {_normalize_material_dir_path(d) for d in report['not_found_materials']}
    total_operations = max(total_models + total_material_candidates + max(len(missing_materials), 1), 1)
    if progress_callback:
        progress_callback(processed_operations, total_operations)
    print('')
    print('Starting Missing Material Recovery...')
    print(f'Content folder: {folder_path}')
    print(f'Content pack search root: {search_root}')
    print(f'Missing material files to recover: {len(missing_materials)}')
    print(f'Missing cdmaterials directories to recover: {len(missing_dirs)}')
    material_index = {}
    pack_summaries = []
    for pack_folder, content_root in pack_roots:
        indexed_here = 0
        for candidate in content_root.rglob('*'):
            if not candidate.is_file() or candidate.suffix.lower() not in MATERIAL_EXTS:
                continue
            rel_path = _n(str(candidate.relative_to(content_root)))
            if not rel_path.startswith('materials/'):
                continue
            material_index.setdefault(rel_path, {'source_path': candidate, 'rel_path': rel_path, 'pack_name': pack_folder.name})
            indexed_here += 1
            emit_progress()
        pack_summaries.append((pack_folder.name, content_root, indexed_here))
    for pack_name, content_root, indexed_here in pack_summaries:
        root_name = 'pack root' if content_root == search_root / pack_name else str(content_root.relative_to(search_root / pack_name))
        print(f'  - Indexed {indexed_here} material files from {pack_name} ({root_name})')
    already_present = 0
    found_matches = 0
    still_missing = []
    copied_files = []
    copied_destinations = set()
    copied_size = 0
    recovery_rows = []
    for material_path in missing_materials:
        source_vmt_key = f'materials/{material_path}.vmt'
        destination_vmt = folder_path / source_vmt_key
        if destination_vmt.exists():
            already_present += 1
            recovery_rows.append({'material': material_path, 'status': 'Already present', 'source': '', 'copied': []})
            emit_progress()
            continue
        source_vmt_info = material_index.get(source_vmt_key)
        if not source_vmt_info:
            still_missing.append(material_path)
            recovery_rows.append({'material': material_path, 'status': 'Missing', 'source': '', 'copied': []})
            emit_progress()
            continue
        found_matches += 1
        files_to_copy = [source_vmt_info]
        related_vtfs = sorted(_extract_related_vtf_paths(source_vmt_info['source_path']))
        for related_vtf in related_vtfs:
            related_source_info = material_index.get(related_vtf)
            if related_source_info:
                files_to_copy.append(related_source_info)
        copied_for_material = []
        for file_info in files_to_copy:
            source_file = file_info['source_path']
            rel_path = file_info['rel_path']
            destination_path = folder_path / rel_path
            if destination_path.exists() or rel_path in copied_destinations:
                continue
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_path)
            copied_destinations.add(rel_path)
            copied_for_material.append(rel_path)
            copied_files.append(rel_path)
            copied_size += source_file.stat().st_size
        recovery_rows.append({'material': material_path, 'status': 'Recovered' if copied_for_material else 'Found (nothing new copied)', 'source': str(source_vmt_info['source_path']), 'copied': copied_for_material})
        emit_progress()
    dir_recovered = 0
    dir_recovery_rows = []
    material_status = report['material_status']
    for mat_dir, status in material_status.items():
        if status['found']:
            continue
        for vmt_rel in status.get('expected_vmts', {}):
            if vmt_rel in copied_destinations:
                continue
            destination_vmt = folder_path / vmt_rel
            if destination_vmt.exists():
                continue
            source_vmt_info = material_index.get(vmt_rel)
            if not source_vmt_info:
                continue
            source_file = source_vmt_info['source_path']
            destination_vmt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_vmt)
            copied_destinations.add(vmt_rel)
            copied_files.append(vmt_rel)
            copied_size += source_file.stat().st_size
            dir_recovered += 1
            dir_recovery_rows.append(vmt_rel)
            for related_vtf in sorted(_extract_related_vtf_paths(source_file)):
                if related_vtf in copied_destinations:
                    continue
                related_dest = folder_path / related_vtf
                if related_dest.exists():
                    continue
                related_info = material_index.get(related_vtf)
                if not related_info:
                    continue
                related_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(related_info['source_path'], related_dest)
                copied_destinations.add(related_vtf)
                copied_files.append(related_vtf)
                copied_size += related_info['source_path'].stat().st_size
                dir_recovery_rows.append(related_vtf)
    if dir_recovered:
        print(f'  - Recovered {dir_recovered} files referenced by missing cdmaterials directories')
    final_report = _collect_model_materials_status(folder_path, gmod_dir=gmod_dir)
    final_missing_dirs = sorted(final_report['not_found_materials'])
    final_missing_materials = sorted(final_report['missing_texture_files'])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write('# Missing Materials Recovery Report\n\n')
        handle.write(f'**Content Folder:** `{folder_path}`\n\n')
        handle.write(f'**Search Root:** `{search_root}`\n\n')
        handle.write(f"**Total Models Scanned:** {report['total_models']}\n")
        handle.write(f'**Missing Material Files Detected:** {len(missing_materials)}\n')
        handle.write(f'**Missing cdmaterials Directories:** {len(missing_dirs)}\n')
        handle.write(f'**Matches Found In Packs:** {found_matches}\n')
        handle.write(f'**Files Copied:** {len(copied_files)}\n')
        handle.write(f'**Still Missing cdmaterials Directories:** {len(final_missing_dirs)}\n')
        handle.write(f'**Still Missing Material Files:** {len(final_missing_materials)}\n\n')
        size_mb = copied_size / (1024 * 1024)
        size_str = f'{size_mb / 1024:.2f} GB' if size_mb >= 1024 else f'{size_mb:.2f} MB'
        handle.write('## What changed\n\n')
        handle.write(f'- Copied `{len(copied_files)}` material asset files ({size_str}) into the content folder.\n')
        handle.write(f'- Recovered `{found_matches}` missing individual texture materials from content packs.\n')
        handle.write(f'- Recovered `{dir_recovered}` files by scanning missing cdmaterials directories.\n')
        handle.write(f'- `{already_present}` materials were already present and left unchanged.\n')
        if final_missing_dirs or final_missing_materials:
            handle.write(f'- `{len(final_missing_dirs)}` cdmaterials directories and `{len(final_missing_materials)}` material files remain missing after verification.\n')
        else:
            handle.write('- Finder verification passed after recovery; no missing materials remain.\n')
        handle.write('\n---\n\n')
        if recovery_rows:
            handle.write('## Recovery Results\n\n')
            for row in recovery_rows:
                handle.write(f"### `{row['material']}`\n\n")
                handle.write(f"- Status: {row['status']}\n")
                if row['source']:
                    handle.write(f"- Source: `{row['source']}`\n")
                if row['copied']:
                    handle.write('- Copied files:\n')
                    for copied_path in row['copied']:
                        handle.write(f'  - `{copied_path}`\n')
                handle.write('\n')
        if dir_recovery_rows:
            handle.write('## Files Recovered from Missing Directories\n\n')
            handle.write(f'These {len(dir_recovery_rows)} files were copied by scanning content packs for files under the missing cdmaterials directories.\n\n')
            for p in dir_recovery_rows:
                handle.write(f'- `{p}`\n')
            handle.write('\n')
        if show_individual_files:
            material_status = report['material_status']
            not_found_dirs = sorted(report['not_found_materials'])
            if not_found_dirs:
                handle.write('## Individual File Status per Missing Directory\n\n')
                for mat_dir in not_found_dirs:
                    expected_vmts = material_status[mat_dir].get('expected_vmts', {})
                    handle.write(f'### `{mat_dir}`\n\n')
                    if not expected_vmts:
                        handle.write('*(Skin texture names could not be determined)*\n\n')
                        continue
                    recovered_files = sorted((p for p in expected_vmts if (folder_path / p).exists()))
                    absent_files = sorted((p for p in expected_vmts if not (folder_path / p).exists()))
                    if recovered_files:
                        handle.write('**Recovered / present:**\n\n')
                        for p in recovered_files:
                            handle.write(f'- `{p}`\n')
                        handle.write('\n')
                    if absent_files:
                        handle.write('**Still missing:**\n\n')
                        for p in absent_files:
                            handle.write(f'- `{p}`\n')
                        handle.write('\n')
        if final_missing_dirs:
            handle.write('## Still Missing Directories\n\n')
            for mat_dir in final_missing_dirs:
                status = final_report['material_status'].get(mat_dir, {})
                models = sorted(set(status.get('models', [])))
                handle.write(f'### `{mat_dir}`\n\n')
                if models:
                    handle.write('Referenced by:\n')
                    for model_path in models:
                        handle.write(f'- `{model_path}`\n')
                expected_vmts = status.get('expected_vmts', {})
                absent_vmts = sorted((p for p, found in expected_vmts.items() if not found))
                if absent_vmts:
                    handle.write('\nMissing files:\n')
                    for vmt_path in absent_vmts:
                        handle.write(f'- `{vmt_path}`\n')
                handle.write('\n')
        if final_missing_materials:
            handle.write('## Still Missing Material Files\n\n')
            for material_path in final_missing_materials:
                models = sorted(set(final_report['texture_status'].get(material_path, {}).get('models', [])))
                handle.write(f'### `{material_path}`\n\n')
                if models:
                    handle.write('Referenced by:\n')
                    for model_path in models:
                        handle.write(f'- `{model_path}`\n')
                handle.write('\n')
    print('')
    print('Missing Material Recovery Summary:')
    print(f'  - Missing material files scanned: {len(missing_materials)}')
    print(f'  - Matches found in packs: {found_matches}')
    print(f'  - Files copied into content folder: {len(copied_files)}')
    print(f'  - Materials already present by copy time: {already_present}')
    print(f'  - Still missing cdmaterials directories after verification: {len(final_missing_dirs)}')
    print(f'  - Still missing material files after verification: {len(final_missing_materials)}')
    print(f'Report saved to: {output_path}')
    print('See the report for a full explanation of what changed during recovery.')
    if progress_callback:
        progress_callback(total_operations, total_operations)
    return (copied_size, len(copied_files), len(missing_materials), found_matches, len(final_missing_dirs))

def remove_models_with_missing_materials(folder_path, gmod_dir=None, remove=True, output_path=None, progress_callback=None):
    """Find (and optionally remove) model files whose material directories or texture VMTs are missing.

    Args:
        folder_path: Path to the content folder containing the models.
        gmod_dir: Optional path to the Garry's Mod directory for fallback resources.
        remove: When True, delete the model files. When False, only report them.
        output_path: Optional path to write a markdown report of found models.
        progress_callback: Optional callback function(current, total) for progress updates.

    Returns:
        tuple: (bytes_freed, models_found)
    """
    folder_path = Path(folder_path)
    report = _collect_model_materials_status(folder_path, gmod_dir=gmod_dir, progress_callback=progress_callback)
    bad_model_paths = set()
    bad_model_missing = {}
    for entry in report['entries']:
        if 'error' in entry:
            continue
        missing_mats = [m['dir'] for m in entry.get('material_info', []) if not m['found'] and m['dir'].strip()]
        missing_texs = [t['path'] for t in entry.get('texture_info', []) if not t['found']]
        if missing_mats or missing_texs:
            bad_model_paths.add(entry['full_path'])
            bad_model_missing[entry['full_path']] = (missing_mats, missing_texs)
    if not bad_model_paths:
        action = 'remove' if remove else 'find'
        print(f'No models with missing materials found — nothing to {action}.')
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('# Models With Missing Textures Report\n\n')
                f.write(f'**Source Folder:** `{folder_path}`\n\n')
                f.write('No models with missing materials were found.\n')
            print(f'Report saved to: {output_path}')
        return (0, 0)
    model_exts_sorted = sorted(MODEL_EXTS, key=lambda e: -len(e))
    freed = 0
    for mdl_path_str in sorted(bad_model_paths):
        mdl_path = Path(mdl_path_str)
        missing_mats, missing_texs = bad_model_missing[mdl_path_str]
        rel = mdl_path.relative_to(folder_path)
        if remove:
            stem = str(mdl_path)
            for ext in model_exts_sorted:
                if stem.lower().endswith(ext):
                    stem = stem[:-len(ext)]
                    break
            for ext in model_exts_sorted:
                candidate = Path(stem + ext)
                if candidate.exists() and candidate.is_file():
                    try:
                        freed += candidate.stat().st_size
                        candidate.unlink()
                        print(f'  Removed: {candidate.relative_to(folder_path)}')
                    except Exception as e:
                        print(f'  Warning: could not remove {candidate}: {e}')
        else:
            print(f'  {rel}')
            for d in missing_mats:
                print(f'    Missing dir : {d}')
            for t in missing_texs:
                print(f'    Missing tex : {t}')
    if remove:
        print(f'Removed {len(bad_model_paths)} model(s), freed {freed / 1024:.2f} KB')
    else:
        print(f'Found {len(bad_model_paths)} model(s) with missing materials.')
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('# Models With Missing Textures Report\n\n')
            f.write(f'**Source Folder:** `{folder_path}`\n\n')
            f.write(f'**Models with missing textures:** {len(bad_model_paths)}\n\n')
            f.write('---\n\n')
            for mdl_path_str in sorted(bad_model_paths):
                mdl_path = Path(mdl_path_str)
                rel = mdl_path.relative_to(folder_path)
                missing_mats, missing_texs = bad_model_missing[mdl_path_str]
                f.write(f'### `{rel}`\n\n')
                if missing_texs:
                    f.write('**Missing texture files:**\n\n')
                    for t in missing_texs:
                        f.write(f'- `materials/{t}.vmt`\n')
                    f.write('\n')
        print(f'Report saved to: {output_path}')
    return (freed, len(bad_model_paths))

def load_cdmaterials():
    entries = []
    keep = set()
    for base, _, files in os.walk(str(ROOT)):
        fs = FileSystemChain(RawFileSystem(base), get_filesystem(str(GMOD_DIR)))
        for fn in files:
            if not fn.lower().endswith('.mdl'):
                continue
            try:
                mats = extract_cdmaterials(fs, fn)
            except:
                mats = []
            entries.append({'model': str(Path(base) / fn), 'materials': mats})
            for d in mats:
                nd = _n(os.path.join('materials', d.strip('/\\')) + '/')
                keep.add(nd)
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    return keep

def write_models(used):
    paths = [k + '.mdl' for k in used]
    WORKSHOP_FILE.write_text('\n'.join(paths), encoding='utf-8')

def delete_unused_space(category, cats, used):
    freed = 0
    for k, f in cats[category]:
        if k not in used:
            try:
                freed += f.stat().st_size
                f.unlink()
            except:
                pass
    return freed

def write_materials(keep):
    paths = []
    for p in ROOT.rglob('materials/**/*'):
        if p.is_file():
            rel = _n(str(p.relative_to(ROOT)))
            if any((rel.startswith(k) for k in keep)):
                paths.append(rel)
    MATERIALS_FILE.write_text('\n'.join(paths), encoding='utf-8')
    return set(paths)

def delete_unused_materials(used):
    mats = [f for _, f in gather()['material']]
    freed = 0
    for f in mats:
        rel = _n(str(f.relative_to(ROOT)))
        if rel not in used:
            try:
                freed += f.stat().st_size
                f.unlink()
            except:
                pass
    return freed

def clean_empty(root):
    for d in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: -len(str(p))):
        try:
            next(d.iterdir())
        except StopIteration:
            try:
                d.rmdir()
            except:
                pass

def main():
    logging.basicConfig(handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8')], level=logging.INFO, format='%(message)s')
    merge(MERGE_SOURCE, ROOT)
    flatten(ROOT)
    lua = read_lua()
    cats = gather()
    before_models = sum((f.stat().st_size for _, f in cats['model']))
    used_models = {k for k, f in cats['model'] if k + '.mdl' in lua}
    write_models(used_models)
    freed_models = delete_unused_space('model', cats, used_models)
    after_models = before_models - freed_models
    before_sounds = sum((f.stat().st_size for _, f in cats['sound']))
    used_sounds = {k for k, f in cats['sound'] if k in lua}
    freed_sounds = delete_unused_space('sound', cats, used_sounds)
    after_sounds = before_sounds - freed_sounds
    before_particles = sum((f.stat().st_size for _, f in cats['particle']))
    used_particles = {k for k, f in cats['particle'] if k in lua}
    freed_particles = delete_unused_space('particle', cats, used_particles)
    after_particles = before_particles - freed_particles
    before_images = sum((f.stat().st_size for _, f in cats['image']))
    used_images = {k for k, f in cats['image'] if k in lua}
    freed_images = delete_unused_space('image', cats, used_images)
    after_images = before_images - freed_images
    keep = load_cdmaterials()
    before_materials = sum((f.stat().st_size for _, f in cats['material']))
    used_materials = write_materials(keep)
    freed_materials = delete_unused_materials(used_materials)
    after_materials = before_materials - freed_materials
    clean_empty(ROOT)
    print(f'Report:\nModels: before {before_models / GB:.2f} GB, freed {freed_models / GB:.2f} GB, after {after_models / GB:.2f} GB\nSounds: before {before_sounds / GB:.2f} GB, freed {freed_sounds / GB:.2f} GB, after {after_sounds / GB:.2f} GB\nParticles: before {before_particles / GB:.2f} GB, freed {freed_particles / GB:.2f} GB, after {after_particles / GB:.2f} GB\nImages: before {before_images / GB:.2f} GB, freed {freed_images / GB:.2f} GB, after {after_images / GB:.2f} GB\nMaterials: before {before_materials / GB:.2f} GB, freed {freed_materials / GB:.2f} GB, after {after_materials / GB:.2f} GB')
if __name__ == '__main__':
    main()
