def format_size(size: int | float) -> str:
    if size < 1000:
        return f'{int(size)} B'
    if size < 1000000:
        kbs = size / 1000
        return f'{round(kbs, 2)} KB'
    mbs = size / 1000000
    return f'{round(mbs, 2)} MB'
