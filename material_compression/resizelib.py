from PIL import Image
from sourcepp import vtfpp


def resizeVTFImage(
    vtf: vtfpp.VTF,
    path: str,
    max_size: int = 1024,
    best_format: vtfpp.ImageFormat = vtfpp.ImageFormat.DXT1,
) -> dict:
    w = vtf.width
    h = vtf.height
    neww = w
    newh = h
    scale = 1
    if w > max_size or h > max_size:
        maxd = max(w, h)
        scale = max_size / maxd
        neww *= scale
        newh *= scale
    if scale != 1:
        vtf.set_size(int(neww), int(newh), vtfpp.ImageConversion.ResizeFilter.NICE)
        vtf.bake_to_file(path)
        print(f'Verified {path}: resized from {w}x{h} to {int(neww)}x{int(newh)}')
        return {
            'changed': True,
            'status': 'resized',
            'details': f'{w}x{h} -> {int(neww)}x{int(newh)}',
        }
    return {
        'changed': False,
        'status': 'unchanged',
        'details': None,
    }


def cleanupVTF(path: str, max_size: int = 9999) -> dict:
    if not path.endswith('.vtf'):
        return {
            'changed': False,
            'status': 'not_vtf',
            'details': None,
        }
    vtf = vtfpp.VTF(path)
    image_data = vtf.get_image_data_as_rgba8888(0)
    image = Image.frombytes('RGBA', (vtf.width, vtf.height), image_data)
    _, _, _, a = image.split()
    best_format = vtfpp.ImageFormat.DXT1
    if a.getextrema()[0] < 255:
        best_format = vtfpp.ImageFormat.DXT5
    format_changed = False
    if vtf.format != best_format:
        vtf.set_format(best_format)
        format_changed = True
    if vtf.frame_count > 1:
        print('Skipping', path, 'because it has multiple frames.')
        if format_changed:
            vtf.bake_to_file(path)
            return {
                'changed': True,
                'status': 'format_only',
                'details': 'multiple frames',
            }
        return {
            'changed': False,
            'status': 'skipped_multiframe',
            'details': None,
        }
    if vtf.width > max_size or vtf.height > max_size:
        resize_result = resizeVTFImage(vtf, path, max_size, best_format)
        if resize_result['changed']:
            resize_result['status'] = 'resized_and_reformatted' if format_changed else 'resized'
        return resize_result
    if format_changed:
        vtf.bake_to_file(path)
        return {
            'changed': True,
            'status': 'reformatted',
            'details': None,
        }
    return {
        'changed': False,
        'status': 'unchanged',
        'details': None,
    }
