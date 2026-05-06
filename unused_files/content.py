import os
import re
import shutil
from pathlib import Path
from collections import defaultdict
from srctools.filesys import RawFileSystem
from srctools.mdl import Model
from utils.removal_tracker import get_tracker
from utils.remove_empty_folders import remove_empty_folders
SOUND_EXTS = {'.wav', '.mp3', '.ogg', '.flac', '.aac'}
PARTICLE_EXTS = {'.pcf'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.tga', '.dds', '.bmp', '.gif'}
MATERIAL_EXTS = {'.vmt', '.vtf'}
MODEL_EXTS = {'.mdl', '.vvd', '.phy', '.vtx', '.ani', '.sw.vtx', '.dx80.vtx', '.dx90.vtx', '.xbox.vtx'}

def _n(p):
    return p.replace('\\', '/').lower()

def check_asset_reference(asset_path, lua_content_lower, prefix_to_remove=None):
    """Check if an asset file is referenced in lua content using various patterns.
    
    Assets in Garry's Mod can be referenced in multiple ways:
    - Full path: "sounds/weapons/pistol/fire.wav"
    - Without prefix: "weapons/pistol/fire.wav" (if prefix_to_remove is "sounds/")
    - Without extension: "sounds/weapons/pistol/fire" or "weapons/pistol/fire"
    - Just filename: "fire.wav" or "fire"
    
    Args:
        asset_path: Normalized asset path (e.g., "sounds/weapons/pistol/fire.wav")
        lua_content_lower: Lowercase lua content to search in
        prefix_to_remove: Optional prefix to remove (e.g., "sounds/", "materials/", "models/")
    
    Returns:
        True if any reference pattern is found, False otherwise
    """
    asset_path = asset_path.lower()
    if asset_path in lua_content_lower:
        return True
    if prefix_to_remove and asset_path.startswith(prefix_to_remove):
        path_without_prefix = asset_path[len(prefix_to_remove):]
        if path_without_prefix in lua_content_lower:
            return True
    if '.' in asset_path:
        path_without_ext = asset_path.rsplit('.', 1)[0]
        if path_without_ext in lua_content_lower:
            return True
        if prefix_to_remove and path_without_ext.startswith(prefix_to_remove):
            path_without_prefix_ext = path_without_ext[len(prefix_to_remove):]
            if path_without_prefix_ext in lua_content_lower:
                return True
    filename = asset_path.split('/')[-1]
    filename_no_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename
    if len(filename_no_ext) > 4:
        quoted_pattern = f"""["\\']([^"\\']*{re.escape(filename_no_ext)}[^"\\']*)["\\']"""
        if re.search(quoted_pattern, lua_content_lower):
            return True
        path_keywords = ['sound', 'model', 'material', 'texture', 'particle', 'file', 'path', 'resource']
        for keyword in path_keywords:
            pattern = f'{keyword}[.\\w]*\\([^)]*{re.escape(filename_no_ext)}'
            if re.search(pattern, lua_content_lower):
                return True
    return False

def check_sound_reference(sound_path, lua_content_lower):
    """Check if a sound file is referenced in lua content using various patterns."""
    return check_asset_reference(sound_path, lua_content_lower, prefix_to_remove='sounds/')

def read_lua_content(lua_path):
    """Read all lua files from the specified path using addon_merge_clean_split.py methodology."""
    parts = []
    lua_dir = Path(lua_path)
    for p in lua_dir.rglob('*.lua'):
        try:
            parts.append(p.read_text('utf-8', 'ignore'))
        except:
            pass
    return _n('\n'.join(parts))

def gather_assets(content_path):
    """Gather all assets by category using addon_merge_clean_split.py methodology."""
    cats = defaultdict(list)
    me = sorted(MODEL_EXTS, key=lambda e: -len(e))
    root_path = Path(content_path)
    for f in root_path.rglob('*'):
        if not f.is_file():
            continue
        rel = _n(str(f.relative_to(root_path)))
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

def unused_content(path, remove=False, lua_path=None, whitelist=None, save_ambiguous_to=None, save_used_to=None, save_unused_to=None, progress_callback=None, materials_only=False, models_only=False, textures_only=False, backup_dir=None):
    """Find unused content using addon_merge_clean_split.py methodology alongside lua folder support.
    
    Args:
        path: Content folder path
        remove: Whether to remove unused files
        lua_path: Optional path to lua folder for scanning references
        whitelist: Optional set of normalized file paths (relative to content folder) that should not be removed
        save_ambiguous_to: Optional file path to save ambiguous paths and localizations to
        save_used_to: Optional file path to save used files report to (markdown format)
        save_unused_to: Optional file path to save unused files list to (text format, one path per line)
        progress_callback: Optional callback function(current, total) for progress updates
        materials_only: When True, only report unused materials from model material directories
        models_only: When True, only report/remove unused models and their sidecar files
        textures_only: When True with materials_only, only target `.vtf` texture files
        backup_dir: Optional folder where removed files should be moved instead of deleted
    """
    from collections import defaultdict
    import utils.formatting
    if materials_only and models_only:
        raise ValueError('materials_only and models_only cannot both be enabled')
    if textures_only and (not materials_only):
        raise ValueError('textures_only requires materials_only=True')
    unused_sizes = 0
    unused_count = 0
    folder_stats = defaultdict(lambda: {'count': 0, 'size': 0, 'files': []})
    ambiguous_paths = []
    localization_files = []
    unused_files_list = []
    tracker = get_tracker()
    progress_current = 0
    progress_total = 0

    def update_progress(stage_name, current=None, total=None):
        """Update progress and emit callback if available."""
        nonlocal progress_current, progress_total
        if progress_callback:
            if current is not None:
                progress_current = current
            if total is not None:
                progress_total = total
            if progress_total > 0:
                progress_callback(progress_current, progress_total)
            else:
                progress_callback(0, 0)
    whitelist_was_none = whitelist is None
    if whitelist is None:
        whitelist = set()
    else:
        whitelist = {_n(str(p)) for p in whitelist}
    print('=' * 80)
    print('🔍 FINDING UNUSED CONTENT')
    print('=' * 80)
    print(f'📂 Content folder: {path}')
    if lua_path:
        print(f'📜 Lua folder: {lua_path}')
    else:
        print('📜 Lua folder: Not specified (will only check direct references)')
    print(f'🛡️  Whitelist entries: {len(whitelist)}')
    print(f"🗑️  Remove mode: {('Enabled' if remove else 'Disabled (scan only)')}")
    print()
    print('📦 Gathering assets from content folder...')
    update_progress('Gathering assets')
    cats = gather_assets(path)
    total_files = 0
    category_counts = {}
    for category in ['model', 'sound', 'particle', 'image', 'material']:
        if category == 'model':
            model_count = 0
            for model_rel, _ in cats['model']:
                for ext in MODEL_EXTS:
                    format_path = os.path.join(path, model_rel + ext)
                    if os.path.exists(format_path):
                        total_files += 1
                        model_count += 1
            category_counts[category] = model_count
        elif category == 'material':
            material_count = 0
            for material_rel, _ in cats['material']:
                for ext in ['.vmt', '.vtf']:
                    material_path = os.path.join(path, material_rel + ext)
                    if os.path.exists(material_path):
                        total_files += 1
                        material_count += 1
            category_counts[category] = material_count
        else:
            count = len(cats[category])
            total_files += count
            category_counts[category] = count
    print(f'✅ Found {total_files} total files to analyze:')
    for cat, count in category_counts.items():
        if count > 0:
            print(f'   • {cat.capitalize()}: {count} files')
    print()
    update_progress('Gathering assets', 0, total_files)
    lua_content = ''
    lua_files = []
    if lua_path:
        print(f'📜 Reading Lua files from: {lua_path}')
        lua_dir = Path(lua_path)
        lua_files = list(lua_dir.rglob('*.lua'))
        print(f'   Found {len(lua_files)} Lua files to scan')
        lua_parts = []
        for i, p in enumerate(lua_files):
            try:
                content = p.read_text('utf-8', 'ignore')
                lua_parts.append(content)
                if (i + 1) % 10 == 0 or i == len(lua_files) - 1:
                    print(f'   Reading... {i + 1}/{len(lua_files)} files ({(i + 1) / len(lua_files) * 100:.1f}%)')
                if progress_callback and len(lua_files) > 0:
                    update_progress('Reading Lua files', i + 1, len(lua_files))
            except Exception as e:
                print(f'   ⚠️  Warning: Could not read {p}: {e}')
        lua_content = _n('\n'.join(lua_parts))
        print(f'✅ Loaded {len(lua_content)} characters from {len(lua_files)} Lua files\n')
    else:
        print('⚠️  No Lua folder specified - will only check for direct file references\n')

    def is_whitelisted(file_path):
        """Check if a file path is in the whitelist.
        
        Checks both the exact file path and all parent directories.
        This means if a directory is whitelisted, all files in it are protected.
        """
        if not whitelist:
            return False
        try:
            rel_path = _n(str(Path(file_path).relative_to(path)))
        except ValueError:
            rel_path = _n(str(file_path))
        path_parts = rel_path.split('/')
        for i in range(len(path_parts), 0, -1):
            check_path = '/'.join(path_parts[:i])
            if check_path in whitelist:
                return True
        return False

    def record_deletion(file_path, file_size):
        """Record a file deletion for reporting purposes."""
        nonlocal unused_sizes, unused_count
        try:
            folder = os.path.relpath(str(Path(file_path).parent), path)
            rel_path = os.path.relpath(str(file_path), path).replace('\\', '/')
        except ValueError:
            folder = str(Path(file_path).parent)
            rel_path = str(file_path).replace('\\', '/')
        folder_stats[folder]['count'] += 1
        folder_stats[folder]['size'] += file_size
        folder_stats[folder]['files'].append(str(Path(file_path).name))
        unused_sizes += file_size
        unused_count += 1
        unused_files_list.append(rel_path)
    lua_content_lower = lua_content.lower()
    print('🔍 Scanning Lua code for asset references...')
    used_models = {k for k, f in cats['model'] if k + '.mdl' in lua_content_lower}
    used_sounds = {k for k, f in cats['sound'] if check_sound_reference(k, lua_content_lower)}
    used_particles = {k for k, f in cats['particle'] if check_asset_reference(k, lua_content_lower, prefix_to_remove='particles/')}
    used_images = {k for k, f in cats['image'] if check_asset_reference(k, lua_content_lower)}
    print(f'   • Models referenced: {len(used_models)}')
    print(f'   • Sounds referenced: {len(used_sounds)}')
    print(f'   • Particles referenced: {len(used_particles)}')
    print(f'   • Images referenced: {len(used_images)}')
    print()
    all_file_paths = []
    for category in ['model', 'sound', 'particle', 'image', 'material']:
        for rel_path, file_path in cats[category]:
            if category == 'model':
                for ext in MODEL_EXTS:
                    full_path = os.path.join(path, rel_path + ext)
                    if os.path.exists(full_path):
                        all_file_paths.append((_n(str(Path(full_path).relative_to(path))), category, rel_path))
            elif category == 'material':
                for ext in ['.vmt', '.vtf']:
                    full_path = os.path.join(path, rel_path + ext)
                    if os.path.exists(full_path):
                        all_file_paths.append((_n(str(Path(full_path).relative_to(path))), category, rel_path))
            else:
                all_file_paths.append((_n(rel_path), category, rel_path))
    used_materials = set()
    for k, f in cats['material']:
        if k in lua_content_lower:
            used_materials.add(k)
            continue
        material_refs = [k, f'materials/{k}', f'{k}.vmt', f'{k}.vtf', f'materials/{k}.vmt', f'materials/{k}.vtf']
        if any((ref in lua_content_lower for ref in material_refs)):
            used_materials.add(k)
    print('🔗 Analyzing model dependencies (materials and textures)...')
    update_progress('Analyzing dependencies', 0, total_files)
    fs = RawFileSystem(path)
    all_model_vmts = {}
    vmt_used_count = {}
    vmf_used_count = {}
    used_material_dirs = set()
    model_dependency_source = [(model_rel, model_file) for model_rel, model_file in cats['model'] if model_rel in used_models] if materials_only else list(cats['model'])
    model_count = 0
    total_models = len(model_dependency_source)
    used_model_count = 0
    for model_rel, model_file in sorted(model_dependency_source, key=lambda item: item[0]):
        if model_rel in used_models:
            used_model_count += 1
        try:
            model = Model(fs, fs[model_rel + '.mdl'])
            all_model_vmts[model_rel + '.mdl'] = []
            texture_count = 0
            for tex in model.iter_textures():
                all_model_vmts[model_rel + '.mdl'].append(tex)
                tex_normalized = _n(tex)
                if tex_normalized.endswith('.vmt'):
                    tex_normalized = tex_normalized[:-4]
                vmt_used_count[tex_normalized] = vmt_used_count.get(tex_normalized, 0) + 1
                texture_count += 1
            try:
                cdmaterials = getattr(model, 'cdmaterials', [])
                for mat_dir in cdmaterials:
                    if not mat_dir or not mat_dir.strip():
                        continue
                    mat_dir_normalized = _n(mat_dir.replace('\\', '/'))
                    if mat_dir_normalized.endswith('/'):
                        mat_dir_normalized = mat_dir_normalized[:-1]
                    if not mat_dir_normalized.startswith('materials/'):
                        mat_dir_normalized = f'materials/{mat_dir_normalized}'
                    used_material_dirs.add(mat_dir_normalized)
            except:
                pass
        except Exception as e:
            pass
        model_count += 1
        if model_count % 50 == 0 or model_count == total_models:
            print(f'   Analyzing models... {model_count}/{total_models} ({model_count / total_models * 100:.1f}%)')
        if progress_callback and total_models > 0:
            update_progress('Analyzing models', model_count, total_models)
    print(f'✅ Analyzed {total_models} models ({used_model_count} referenced in Lua), found {len(vmt_used_count)} referenced materials')
    print(f'   Found {len(used_material_dirs)} material directories from cdmaterials\n')
    print('🎨 Extracting texture references from materials...')
    vmt_count = 0
    total_vmts = sum((len(vmts) for vmts in all_model_vmts.values()))
    for model, vmts in all_model_vmts.items():
        for vmt_path in vmts:
            vmt_count += 1
            vmt_full_path = os.path.join(path, vmt_path)
            if os.path.exists(vmt_full_path):
                try:
                    with open(vmt_full_path, 'r', encoding='utf-8') as f:
                        from srctools.vmt import Material
                        vmt = Material.parse(f, filename=vmt_path)
                    for vmtfield in vmt.items():
                        if vmtfield[0].startswith('$basetexture'):
                            vtf = os.path.normpath(vmtfield[1])
                            vtf_normalized = _n(vtf)
                            if vtf_normalized.endswith('.vtf'):
                                vtf_normalized = vtf_normalized[:-4]
                            vmf_used_count[vtf_normalized] = vmf_used_count.get(vtf_normalized, 0) + 1
                except:
                    pass
            if vmt_count % 100 == 0 or vmt_count == total_vmts:
                print(f'   Processing materials... {vmt_count}/{total_vmts} ({vmt_count / total_vmts * 100:.1f}%)' if total_vmts > 0 else '')
    if total_vmts > 0:
        print(f'✅ Processed {vmt_count} materials, found {len(vmf_used_count)} referenced textures\n')
    print('🔎 Checking for ambiguous paths (files that might be referenced dynamically)...')
    root_path = Path(path)
    resource_path = root_path / 'resource'
    if resource_path.exists():
        for txt_file in resource_path.rglob('*.txt'):
            try:
                rel_path = _n(str(txt_file.relative_to(path)))
                localization_files.append(rel_path)
            except:
                pass
    if localization_files:
        print(f'   Found {len(localization_files)} localization files')
    total_files_to_check = len(all_file_paths)
    checked_count = 0
    for file_rel, category, rel_path in all_file_paths:
        checked_count += 1
        if checked_count % 100 == 0:
            print(f'   Checking ambiguous paths... {checked_count}/{total_files_to_check} files ({checked_count / total_files_to_check * 100:.1f}%)')
        file_name = Path(file_rel).name.lower()
        file_stem = Path(file_rel).stem.lower()
        is_ambiguous = False
        if len(file_stem) <= 4:
            continue
        is_used = False
        if category == 'model' and rel_path in used_models:
            is_used = True
        elif category == 'sound' and rel_path in used_sounds:
            is_used = True
        elif category == 'particle' and rel_path in used_particles:
            is_used = True
        elif category == 'image' and rel_path in used_images:
            is_used = True
        elif category == 'material' and rel_path in used_materials:
            is_used = True
        if is_used:
            continue
        if file_stem not in lua_content_lower:
            continue
        quoted_pattern = f"""["\\']([^"\\']*{re.escape(file_stem)}[^"\\']*)["\\']"""
        keyword_pattern = f'(sound|model|material|texture|particle|file|path|resource)[.\\w]*\\([^)]*{re.escape(file_stem)}'
        if re.search(quoted_pattern, lua_content_lower) or re.search(keyword_pattern, lua_content_lower):
            is_ambiguous = True
        if is_ambiguous:
            ambiguous_paths.append(file_rel)
    if ambiguous_paths:
        print(f'   Found {len(ambiguous_paths)} potentially ambiguous paths (may need manual review)')
        print(f'   ⚠️  These files were NOT automatically whitelisted to avoid false positives.')
        print(f"   ⚠️  Please review the ambiguous paths report and manually add to whitelist if they're actually used.")
    print()
    if materials_only:

        def material_variants(material_rel):
            normalized = _n(material_rel)
            variants = {normalized}
            if normalized.startswith('materials/'):
                variants.add(normalized[len('materials/'):])
            else:
                variants.add(f'materials/{normalized}')
            return variants

        def material_is_used_by_model(material_rel):
            variants = material_variants(material_rel)
            if any((vmt_used_count.get(variant, 0) > 0 for variant in variants)):
                return True
            if any((vmf_used_count.get(variant, 0) > 0 for variant in variants)):
                return True
            return False

        def material_is_in_model_directory(material_rel):
            variants = material_variants(material_rel)
            for material_dir in used_material_dirs:
                material_dir = _n(material_dir).rstrip('/')
                for variant in variants:
                    if variant.startswith(material_dir + '/'):
                        return True
            return False
        print('Processing model materials only...')
        material_rel_map = {}
        for material_rel, _material_file in cats['material']:
            normalized_material_rel = _n(material_rel)
            if material_is_in_model_directory(normalized_material_rel):
                material_rel_map.setdefault(normalized_material_rel, material_rel)
        model_materials = [material_rel_map[key] for key in sorted(material_rel_map.keys())]
        target_exts = ['.vtf'] if textures_only else ['.vmt', '.vtf']
        total_materials = len(model_materials)
        processed_materials = 0
        unused_material_count = 0
        for idx, material_rel in enumerate(model_materials, 1):
            is_used = False
            if textures_only:
                variants = material_variants(material_rel)
                is_used = any((vmf_used_count.get(variant, 0) > 0 for variant in variants))
            else:
                is_used = material_is_used_by_model(material_rel)
            if not is_used:
                for ext in target_exts:
                    material_path = os.path.join(path, material_rel + ext)
                    if not os.path.exists(material_path) or is_whitelisted(material_path):
                        continue
                    file_size = os.path.getsize(material_path)
                    unused_material_count += 1
                    if unused_material_count <= 5 or unused_material_count % 50 == 0:
                        print(f'   Found unused: {os.path.basename(material_path)}')
                    record_deletion(material_path, file_size)
                    if remove:
                        rel_path = os.path.relpath(material_path, path).replace('\\', '/')
                        if backup_dir:
                            backup_path = os.path.join(backup_dir, rel_path)
                            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                            shutil.move(material_path, backup_path)
                        else:
                            os.remove(material_path)
                        tracker.record_file_removal(rel_path, 'Remove Unused Material Textures' if textures_only else 'Remove Unused Materials', file_size, 'Unused model texture file' if textures_only else 'Unused model material file')
                    processed_materials += 1
                    update_progress('Processing materials', processed_materials, total_files)
            if idx % 100 == 0 or idx == total_materials:
                print(f'   Progress: {idx}/{total_materials} materials checked, {unused_material_count} unused files found')
        print()
        print('=' * 80)
        print('TEXTURE SUMMARY' if textures_only else 'MATERIAL SUMMARY')
        print('=' * 80)
        print(f'Total model-directory materials analyzed: {len(model_materials)}')
        print(f"Unused {('texture' if textures_only else 'material')} files found: {unused_count}")
        print(f"Total space {('saved' if remove else 'that can be saved')}: {utils.formatting.format_size(unused_sizes)}")
        if remove and backup_dir:
            print(f'Backup folder: {backup_dir}')
        if save_unused_to:
            try:
                unused_files_list_sorted = sorted(set(unused_files_list))
                with open(save_unused_to, 'w', encoding='utf-8') as f:
                    report_title = 'Unused Material Textures Report' if textures_only else 'Unused Materials Report'
                    report_label = 'texture' if textures_only else 'material'
                    f.write(f'# {report_title}\n\n')
                    f.write(f'Total unused {report_label} files: {len(unused_files_list_sorted)}\n')
                    f.write(f"Total space {('saved' if remove else 'that can be saved')}: {utils.formatting.format_size(unused_sizes)}\n\n")
                    f.write('---\n\n')
                    f.write(f'## Unused {report_label.capitalize()} Files (one per line)\n\n')
                    for file_path in unused_files_list_sorted:
                        f.write(f'{file_path}\n')
                print(f"\nSaved unused {('material textures' if textures_only else 'materials')} list ({len(unused_files_list_sorted)} files) to: {save_unused_to}")
            except Exception as e:
                print(f"Warning: Could not save unused {('material textures' if textures_only else 'materials')} list to file: {e}")
        return (unused_sizes, unused_count)
    print('🗑️  Processing models...')
    processed_files = 0
    unused_model_files = 0
    total_models_to_check = len(cats['model'])
    for idx, (model_rel, model_file) in enumerate(cats['model'], 1):
        if model_rel not in used_models:
            for ext in MODEL_EXTS:
                format_path = os.path.join(path, model_rel + ext)
                if os.path.exists(format_path):
                    if is_whitelisted(format_path):
                        pass
                    else:
                        file_size = os.path.getsize(format_path)
                        unused_model_files += 1
                        if unused_model_files <= 5 or unused_model_files % 50 == 0:
                            print(f'   Found unused: {os.path.basename(format_path)}')
                        record_deletion(format_path, file_size)
                        if remove:
                            os.remove(format_path)
                            rel_path = os.path.relpath(format_path, path).replace('\\', '/')
                            tracker.record_file_removal(rel_path, 'Remove Unused Content', file_size, 'Unused model file')
                    processed_files += 1
                    update_progress('Processing models', processed_files, total_files)
        if idx % 100 == 0 or idx == total_models_to_check:
            print(f'   Progress: {idx}/{total_models_to_check} models checked, {unused_model_files} unused files found')
            for vmt in all_model_vmts.get(model_rel + '.mdl', []):
                vmt_used_count[vmt] = vmt_used_count.get(vmt, 0) - 1
            for vtf in []:
                vmf_used_count[vtf] = vmf_used_count.get(vtf, 0) - 1
    if unused_model_files > 0:
        print(f'✅ Models: Found {unused_model_files} unused model files\n')
    else:
        print('✅ Models: All model files are in use\n')
    if models_only:
        print('\n' + '=' * 80)
        print('MODEL SUMMARY')
        print('=' * 80)
        print(f"Total models analyzed: {len(cats['model'])}")
        print(f'Unused model files found: {unused_count}')
        print(f"Total space {('saved' if remove else 'that can be saved')}: {utils.formatting.format_size(unused_sizes)}")
        return (unused_sizes, unused_count)
    print('🔊 Processing sounds...')
    unused_sound_count = 0
    total_sounds = len(cats['sound'])
    for idx, (sound_rel, sound_file) in enumerate(cats['sound'], 1):
        if sound_rel not in used_sounds:
            if is_whitelisted(str(sound_file)):
                pass
            else:
                file_size = sound_file.stat().st_size
                unused_sound_count += 1
                if unused_sound_count <= 5 or unused_sound_count % 50 == 0:
                    print(f'   Found unused: {sound_file.name}')
                record_deletion(str(sound_file), file_size)
                if remove:
                    sound_file.unlink()
                    rel_path = os.path.relpath(str(sound_file), path).replace('\\', '/')
                    tracker.record_file_removal(rel_path, 'Remove Unused Content', file_size, 'Unused sound file')
            processed_files += 1
            update_progress('Processing sounds', processed_files, total_files)
        if idx % 100 == 0 or idx == total_sounds:
            print(f'   Progress: {idx}/{total_sounds} sounds checked, {unused_sound_count} unused files found')
    if unused_sound_count > 0:
        print(f'✅ Sounds: Found {unused_sound_count} unused sound files\n')
    else:
        print('✅ Sounds: All sound files are in use\n')
    print('✨ Processing particles...')
    unused_particle_count = 0
    total_particles = len(cats['particle'])
    for idx, (particle_rel, particle_file) in enumerate(cats['particle'], 1):
        if particle_rel not in used_particles:
            if is_whitelisted(str(particle_file)):
                pass
            else:
                file_size = particle_file.stat().st_size
                unused_particle_count += 1
                if unused_particle_count <= 5 or unused_particle_count % 50 == 0:
                    print(f'   Found unused: {particle_file.name}')
                record_deletion(str(particle_file), file_size)
                if remove:
                    particle_file.unlink()
                    rel_path = os.path.relpath(str(particle_file), path).replace('\\', '/')
                    tracker.record_file_removal(rel_path, 'Remove Unused Content', file_size, 'Unused particle file')
            processed_files += 1
            update_progress('Processing particles', processed_files, total_files)
        if idx % 50 == 0 or idx == total_particles:
            print(f'   Progress: {idx}/{total_particles} particles checked, {unused_particle_count} unused files found')
    if unused_particle_count > 0:
        print(f'✅ Particles: Found {unused_particle_count} unused particle files\n')
    else:
        print('✅ Particles: All particle files are in use\n')
    print('🖼️  Processing images...')
    unused_image_count = 0
    total_images = len(cats['image'])
    for idx, (image_rel, image_file) in enumerate(cats['image'], 1):
        if image_rel not in used_images:
            if is_whitelisted(str(image_file)):
                pass
            else:
                file_size = image_file.stat().st_size
                unused_image_count += 1
                if unused_image_count <= 5 or unused_image_count % 50 == 0:
                    print(f'   Found unused: {image_file.name}')
                record_deletion(str(image_file), file_size)
                if remove:
                    image_file.unlink()
                    rel_path = os.path.relpath(str(image_file), path).replace('\\', '/')
                    tracker.record_file_removal(rel_path, 'Remove Unused Content', file_size, 'Unused image file')
            processed_files += 1
            update_progress('Processing images', processed_files, total_files)
        if idx % 100 == 0 or idx == total_images:
            print(f'   Progress: {idx}/{total_images} images checked, {unused_image_count} unused files found')
    if unused_image_count > 0:
        print(f'✅ Images: Found {unused_image_count} unused image files\n')
    else:
        print('✅ Images: All image files are in use\n')
    print('🎨 Processing materials...')
    print('   ⚠️  Materials are not being removed (skipped for safety)')
    print('✅ Materials: Skipped material removal\n')
    print('\n' + '=' * 80)
    print('📊 FINAL SUMMARY')
    print('=' * 80)
    print(f'✅ Analysis complete!')
    print(f'📁 Total files analyzed: {total_files}')
    print(f'🗂️  Unused files found: {unused_count}')
    print(f'💾 Total space that can be saved: {utils.formatting.format_size(unused_sizes)}')
    print()
    print('=' * 80)
    print('DETECTION STATISTICS')
    print('=' * 80)
    print(f'📊 Assets found:')
    print(f"   • Models: {len(cats['model'])} total, {len(used_models)} used, {len(cats['model']) - len(used_models)} unused")
    print(f"   • Sounds: {len(cats['sound'])} total, {len(used_sounds)} used, {len(cats['sound']) - len(used_sounds)} unused")
    print(f"   • Particles: {len(cats['particle'])} total, {len(used_particles)} used, {len(cats['particle']) - len(used_particles)} unused")
    print(f"   • Images: {len(cats['image'])} total, {len(used_images)} used, {len(cats['image']) - len(used_images)} unused")
    print(f"   • Materials: {len(cats['material'])} total, {len(used_materials)} used, {len(cats['material']) - len(used_materials)} unused")
    if lua_path:
        print(f'📜 Lua files scanned: {len(lua_files)}')
        print(f'📝 Lua content size: {len(lua_content)} characters')
    else:
        print(f'⚠️  No Lua folder specified - only direct file references were checked')
    print()
    if folder_stats:
        print('=' * 80)
        print('UNUSED CONTENT REMOVAL REPORT - PER FOLDER BREAKDOWN' if remove else 'UNUSED CONTENT SCAN REPORT - PER FOLDER BREAKDOWN')
        print('=' * 80)
        total_folders = len(folder_stats)
        print(f'Total folders processed: {total_folders}')
        if remove:
            print(f'Total files removed: {unused_count}')
            print(f'Total space saved: {utils.formatting.format_size(unused_sizes)}')
        else:
            print(f'Total unused files found: {unused_count}')
            print(f'Total space that can be saved: {utils.formatting.format_size(unused_sizes)}')
        print()
        sorted_folders = sorted(folder_stats.items(), key=lambda x: x[1]['size'], reverse=True)
        print('PER FOLDER BREAKDOWN (sorted by space saved):')
        print('-' * 80)
        for i, (folder, stats) in enumerate(sorted_folders, 1):
            try:
                rel_folder = os.path.relpath(folder, path)
            except ValueError:
                rel_folder = folder
            percentage = stats['size'] / unused_sizes * 100 if unused_sizes > 0 else 0
            print(f'{i:2d}. {rel_folder}/')
            if remove:
                print(f"    Files removed: {stats['count']}")
                print(f"    Space saved: {utils.formatting.format_size(stats['size'])} ({percentage:.1f}%)")
            else:
                print(f"    Unused files found: {stats['count']}")
                print(f"    Space that can be saved: {utils.formatting.format_size(stats['size'])} ({percentage:.1f}%)")
            if total_folders <= 5:
                max_files = 10
            else:
                max_files = 5
            if len(stats['files']) <= max_files:
                if stats['files']:
                    print(f"    Files: {', '.join(stats['files'])}")
            else:
                extra = len(stats['files']) - max_files
                shown = ', '.join(stats['files'][:max_files])
                print(f'    Files: {shown} ... (+{extra} more)')
            print()
        print('=' * 80)
        print('Tip: Folders are sorted by space saved (largest first)')
        if remove:
            print('Review the results carefully in case anything needs to be restored.')
        else:
            print('Check file lists carefully before removing to avoid deleting needed files!')
    else:
        print('\nNo unused content found!')
        print('All files in your addon appear to be referenced in your Lua code.')
    if save_ambiguous_to:
        try:
            with open(save_ambiguous_to, 'w', encoding='utf-8') as f:
                f.write('# Ambiguous Paths and Localizations\n')
                f.write("# This file contains paths that might be referenced but weren't detected by simple string search\n")
                f.write('# and localization files that might be used by the game engine.\n\n')
                if ambiguous_paths:
                    f.write('# ===== AMBIGUOUS PATHS =====\n')
                    f.write('# Files that exist but might be referenced via variables, string concatenation, or other dynamic methods\n')
                    f.write(f'# Total: {len(ambiguous_paths)}\n\n')
                    for path in sorted(ambiguous_paths):
                        f.write(f'{path}\n')
                    f.write('\n')
                if localization_files:
                    f.write('# ===== LOCALIZATION FILES =====\n')
                    f.write('# Files in resource folder (typically .txt files used for localization)\n')
                    f.write(f'# Total: {len(localization_files)}\n\n')
                    for path in sorted(localization_files):
                        f.write(f'{path}\n')
                    f.write('\n')
                if not ambiguous_paths and (not localization_files):
                    f.write('# No ambiguous paths or localization files found.\n')
            print(f'\n📄 Saved {len(ambiguous_paths)} ambiguous paths and {len(localization_files)} localization files to: {save_ambiguous_to}')
        except Exception as e:
            print(f'Warning: Could not save ambiguous paths and localizations to file: {e}')
    if save_used_to:
        try:
            from datetime import datetime
            used_files_by_category = {'models': [], 'sounds': [], 'particles': [], 'images': [], 'materials': []}
            for model_rel in used_models:
                for ext in MODEL_EXTS:
                    model_path = os.path.join(path, model_rel + ext)
                    if os.path.exists(model_path):
                        rel_path = _n(str(Path(model_path).relative_to(path)))
                        used_files_by_category['models'].append(rel_path)
            for sound_rel in used_sounds:
                rel_path = _n(sound_rel)
                used_files_by_category['sounds'].append(rel_path)
            for particle_rel in used_particles:
                rel_path = _n(particle_rel)
                used_files_by_category['particles'].append(rel_path)
            for image_rel in used_images:
                rel_path = _n(image_rel)
                used_files_by_category['images'].append(rel_path)
            for material_rel in used_materials:
                for ext in ['.vmt', '.vtf']:
                    material_path = os.path.join(path, material_rel + ext)
                    if os.path.exists(material_path):
                        rel_path = _n(str(Path(material_path).relative_to(path)))
                        used_files_by_category['materials'].append(rel_path)
            if 'vmt_used_count' in locals() and 'vmf_used_count' in locals():
                for vmt_path in vmt_used_count.keys():
                    if vmt_used_count[vmt_path] > 0:
                        vmt_full_path = os.path.join(path, vmt_path + '.vmt')
                        if os.path.exists(vmt_full_path):
                            rel_path = _n(str(Path(vmt_full_path).relative_to(path)))
                            if rel_path not in used_files_by_category['materials']:
                                used_files_by_category['materials'].append(rel_path)
                for vtf_path in vmf_used_count.keys():
                    if vmf_used_count[vtf_path] > 0:
                        vtf_full_path = os.path.join(path, vtf_path + '.vtf')
                        if os.path.exists(vtf_full_path):
                            rel_path = _n(str(Path(vtf_full_path).relative_to(path)))
                            if rel_path not in used_files_by_category['materials']:
                                used_files_by_category['materials'].append(rel_path)
            with open(save_used_to, 'w', encoding='utf-8') as f:
                f.write('# Used Files Report\n\n')
                f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f'Content folder: `{path}`\n\n')
                if lua_path:
                    f.write(f'Lua folder: `{lua_path}`\n\n')
                f.write('## Summary\n\n')
                total_used = sum((len(files) for files in used_files_by_category.values()))
                f.write(f'- **Total used files**: {total_used}\n')
                f.write(f"- **Models**: {len(used_files_by_category['models'])}\n")
                f.write(f"- **Sounds**: {len(used_files_by_category['sounds'])}\n")
                f.write(f"- **Particles**: {len(used_files_by_category['particles'])}\n")
                f.write(f"- **Images**: {len(used_files_by_category['images'])}\n")
                f.write(f"- **Materials**: {len(used_files_by_category['materials'])}\n\n")
                f.write('## Used Files by Category\n\n')
                for category in ['models', 'sounds', 'particles', 'images', 'materials']:
                    files = sorted(used_files_by_category[category])
                    if files:
                        f.write(f'### {category.capitalize()} ({len(files)} files)\n\n')
                        for file_path in files:
                            f.write(f'- `{file_path}`\n')
                        f.write('\n')
                    else:
                        f.write(f'### {category.capitalize()} (0 files)\n\n')
                        f.write('*No files found in this category.*\n\n')
                f.write('---\n\n')
                f.write('*Report generated by GM Addon Optimization Tools*\n')
            print(f'\n📄 Saved used files report ({total_used} files) to: {save_used_to}')
        except Exception as e:
            print(f'Warning: Could not save used files report to file: {e}')
    if save_unused_to:
        try:
            unused_files_list_sorted = sorted(set(unused_files_list))
            with open(save_unused_to, 'w', encoding='utf-8') as f:
                f.write('# Unused Files Report\n\n')
                f.write(f'Total unused files: {len(unused_files_list_sorted)}\n')
                f.write(f'Total space that can be saved: {utils.formatting.format_size(unused_sizes)}\n\n')
                f.write('---\n\n')
                f.write('## Unused Files (one per line)\n\n')
                for file_path in unused_files_list_sorted:
                    f.write(f'{file_path}\n')
            print(f'\n📄 Saved unused files list ({len(unused_files_list_sorted)} files) to: {save_unused_to}')
        except Exception as e:
            print(f'Warning: Could not save unused files list to file: {e}')
    if remove:
        print('\n' + '=' * 50)
        print('REMOVING EMPTY FOLDERS')
        print('=' * 50)
        empty_folders_removed = remove_empty_folders(path, progress_callback)
        print(f'Removed {empty_folders_removed} empty folders')
        print('=' * 50)
    return (unused_sizes, unused_count)

def find_ambiguous_paths_detailed(path, lua_path=None, output_file=None):
    """Find ambiguous paths with detailed context about why they're ambiguous.
    
    Ambiguous paths are files that might be referenced but weren't detected by simple string search.
    This function provides detailed information about what part of the filename appears in lua code.
    
    Args:
        path: Content folder path
        lua_path: Optional path to lua folder for scanning references
        output_file: Optional path to save markdown report
    
    Returns:
        List of ambiguous path info dictionaries
    """
    from pathlib import Path as PathLib
    ambiguous_paths_info = []
    localization_files = []
    cats = gather_assets(path)
    lua_content = ''
    lua_files_content = {}
    if lua_path:
        lua_dir = Path(lua_path)
        for p in lua_dir.rglob('*.lua'):
            try:
                content = p.read_text('utf-8', 'ignore')
                rel_lua_path = str(p.relative_to(lua_path))
                lua_files_content[rel_lua_path] = content
                lua_content += content + '\n'
            except:
                pass
    else:
        print('Warning: No lua folder specified. Ambiguous paths require lua scanning.')
        return []
    lua_content_lower = lua_content.lower()
    used_models = {k for k, f in cats['model'] if k + '.mdl' in lua_content_lower}
    used_sounds = {k for k, f in cats['sound'] if k in lua_content_lower}
    used_particles = {k for k, f in cats['particle'] if k in lua_content_lower}
    used_images = {k for k, f in cats['image'] if k in lua_content_lower}
    used_materials = set()
    for k, f in cats['material']:
        if k in lua_content_lower:
            used_materials.add(k)
            continue
        material_refs = [k, f'materials/{k}', f'{k}.vmt', f'{k}.vtf', f'materials/{k}.vmt', f'materials/{k}.vtf']
        if any((ref in lua_content_lower for ref in material_refs)):
            used_materials.add(k)
    all_file_paths = []
    for category in ['model', 'sound', 'particle', 'image', 'material']:
        for rel_path, file_path in cats[category]:
            if category == 'model':
                for ext in MODEL_EXTS:
                    full_path = os.path.join(path, rel_path + ext)
                    if os.path.exists(full_path):
                        all_file_paths.append((_n(str(Path(full_path).relative_to(path))), category, rel_path))
            elif category == 'material':
                for ext in ['.vmt', '.vtf']:
                    full_path = os.path.join(path, rel_path + ext)
                    if os.path.exists(full_path):
                        all_file_paths.append((_n(str(Path(full_path).relative_to(path))), category, rel_path))
            else:
                all_file_paths.append((_n(rel_path), category, rel_path))

    def find_lua_context(search_term, context_chars=100):
        """Find context around a search term in lua files."""
        contexts = []
        search_lower = search_term.lower()
        for lua_file_path, lua_file_content in lua_files_content.items():
            content_lower = lua_file_content.lower()
            if search_lower in content_lower:
                start = 0
                while True:
                    idx = content_lower.find(search_lower, start)
                    if idx == -1:
                        break
                    context_start = max(0, idx - context_chars)
                    context_end = min(len(lua_file_content), idx + len(search_term) + context_chars)
                    context = lua_file_content[context_start:context_end]
                    line_num = lua_file_content[:idx].count('\n') + 1
                    contexts.append({'file': lua_file_path, 'line': line_num, 'context': context.strip(), 'match': search_term})
                    start = idx + 1
                    if len([c for c in contexts if c['file'] == lua_file_path]) >= 3:
                        break
        return contexts[:5]
    for file_rel, category, rel_path in all_file_paths:
        file_name = Path(file_rel).name.lower()
        file_stem = Path(file_rel).stem.lower()
        is_ambiguous = False
        match_type = None
        match_term = None
        if category == 'model':
            if rel_path not in used_models:
                if file_name in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'filename'
                    match_term = Path(file_rel).name
                elif file_stem in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'stem'
                    match_term = Path(file_rel).stem
        elif category == 'sound':
            if rel_path not in used_sounds:
                if file_name in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'filename'
                    match_term = Path(file_rel).name
                elif file_stem in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'stem'
                    match_term = Path(file_rel).stem
        elif category == 'particle':
            if rel_path not in used_particles:
                if file_name in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'filename'
                    match_term = Path(file_rel).name
                elif file_stem in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'stem'
                    match_term = Path(file_rel).stem
        elif category == 'image':
            if rel_path not in used_images:
                if file_name in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'filename'
                    match_term = Path(file_rel).name
                elif file_stem in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'stem'
                    match_term = Path(file_rel).stem
        elif category == 'material':
            material_stem = rel_path
            if material_stem not in used_materials:
                if file_name in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'filename'
                    match_term = Path(file_rel).name
                elif file_stem in lua_content_lower:
                    is_ambiguous = True
                    match_type = 'stem'
                    match_term = Path(file_rel).stem
        if is_ambiguous:
            lua_contexts = find_lua_context(match_term)
            ambiguous_paths_info.append({'file_path': file_rel, 'category': category, 'match_type': match_type, 'match_term': match_term, 'lua_contexts': lua_contexts})
    root_path = Path(path)
    resource_path = root_path / 'resource'
    if resource_path.exists():
        for txt_file in resource_path.rglob('*.txt'):
            try:
                rel_path = _n(str(txt_file.relative_to(path)))
                localization_files.append(rel_path)
            except:
                pass
    if output_file:
        generate_ambiguous_paths_report(ambiguous_paths_info, localization_files, output_file, path, lua_path)
    print('\n' + '=' * 80)
    print('AMBIGUOUS PATHS FROM LUA SCANNING')
    print('=' * 80)
    print(f"These are paths that might be referenced but weren't detected by simple string search.")
    print(f'Total ambiguous paths found: {len(ambiguous_paths_info)}')
    print(f'Total localization files found: {len(localization_files)}')
    print()
    if ambiguous_paths_info:
        print('===== AMBIGUOUS PATHS =====')
        print('Files that exist but might be referenced via variables, string concatenation, or other dynamic methods:')
        print()
        for info in sorted(ambiguous_paths_info, key=lambda x: x['file_path']):
            print(f"  {info['file_path']} (matched by {info['match_type']}: '{info['match_term']}')")
        print()
    if localization_files:
        print('===== LOCALIZATION FILES =====')
        print('Files in resource folder (typically .txt files used for localization):')
        print()
        for path_item in sorted(localization_files):
            print(f'  {path_item}')
        print()
    if not ambiguous_paths_info and (not localization_files):
        print('No ambiguous paths or localization files found.')
        print('All files appear to be properly referenced in your Lua code.')
    print('=' * 80)
    return ambiguous_paths_info

def generate_ambiguous_paths_report(ambiguous_paths_info, localization_files, output_file, content_path, lua_path):
    """Generate a detailed markdown report of ambiguous paths."""
    from datetime import datetime
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('# Ambiguous Paths Report\n\n')
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        if content_path:
            f.write(f'Content folder: `{content_path}`\n\n')
        if lua_path:
            f.write(f'Lua folder: `{lua_path}`\n\n')
        f.write('## Summary\n\n')
        f.write(f'- **Total ambiguous paths found**: {len(ambiguous_paths_info)}\n')
        f.write(f'- **Total localization files found**: {len(localization_files)}\n\n')
        f.write('## What are Ambiguous Paths?\n\n')
        f.write("Ambiguous paths are files that exist in your content folder but weren't detected ")
        f.write('by simple string search in your Lua code. However, parts of their filename or stem ')
        f.write('(filename without extension) appear in your Lua code, suggesting they might be ')
        f.write('referenced via:\n\n')
        f.write('- Variables\n')
        f.write('- String concatenation\n')
        f.write('- Dynamic path construction\n')
        f.write('- Other indirect methods\n\n')
        f.write('**⚠️ Warning**: These files might still be used! Review the Lua context below ')
        f.write('before adding them to your whitelist or removing them.\n\n')
        if ambiguous_paths_info:
            f.write('## Ambiguous Paths\n\n')
            f.write('### How to Use This Report\n\n')
            f.write('1. Review each file path below\n')
            f.write('2. Check the Lua context to see how the filename/stem is used\n')
            f.write('3. If the file is actually used, add it to your whitelist file\n')
            f.write('4. Add one path per line in your whitelist file (relative to content folder)\n\n')
            f.write('### Whitelist Format\n\n')
            f.write('You can copy the file paths below directly into your whitelist file. ')
            f.write('Each path should be on its own line, relative to the content folder.\n\n')
            f.write('Example whitelist entry:\n')
            f.write('```\n')
            f.write('models/player/custom_player.mdl\n')
            f.write('sounds/weapons/custom_gun.wav\n')
            f.write('```\n\n')
            f.write('---\n\n')
            by_category = {}
            for info in ambiguous_paths_info:
                cat = info['category']
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(info)
            for category in sorted(by_category.keys()):
                f.write(f'### {category.capitalize()} Files\n\n')
                for info in sorted(by_category[category], key=lambda x: x['file_path']):
                    f.write(f"#### `{info['file_path']}`\n\n")
                    f.write(f"- **Category**: {info['category']}\n")
                    f.write(f"- **Matched by**: {info['match_type']} (`{info['match_term']}`)\n")
                    f.write(f"- **Full path**: `{info['file_path']}`\n\n")
                    if info['lua_contexts']:
                        f.write('**Lua Context** (where the match was found):\n\n')
                        for i, ctx in enumerate(info['lua_contexts'], 1):
                            f.write(f"**Occurrence {i}** in `{ctx['file']}` (line {ctx['line']}):\n\n")
                            f.write('```lua\n')
                            context_escaped = ctx['context'].replace('```', '\\`\\`\\`')
                            f.write(context_escaped)
                            f.write('\n```\n\n')
                    else:
                        f.write('*No specific Lua context found (match detected but context unavailable)*\n\n')
                    f.write('**Whitelist entry**:\n')
                    f.write('```\n')
                    f.write(f"{info['file_path']}\n")
                    f.write('```\n\n')
                    f.write('---\n\n')
        if localization_files:
            f.write('## Localization Files\n\n')
            f.write('These files in the `resource` folder are typically used by the game engine ')
            f.write('for localization and should generally be kept.\n\n')
            f.write('### Files\n\n')
            for loc_file in sorted(localization_files):
                f.write(f'- `{loc_file}`\n')
            f.write('\n')
        if not ambiguous_paths_info and (not localization_files):
            f.write('## No Ambiguous Paths Found\n\n')
            f.write('All files in your addon appear to be properly referenced in your Lua code.\n')
        f.write('\n---\n\n')
        f.write('*Report generated by GM Addon Optimization Tools*\n')
    print(f'\n📄 Detailed ambiguous paths report saved to: {output_file}')

def find_ambiguous_paths(path, lua_path=None):
    """Find and print ambiguous paths from lua scanning.
    
    Ambiguous paths are files that might be referenced but weren't detected by simple string search.
    These are paths that the find unused content sees as potential ones.
    
    Args:
        path: Content folder path
        lua_path: Optional path to lua folder for scanning references
    """
    find_ambiguous_paths_detailed(path, lua_path, output_file=None)
