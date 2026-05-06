"""
Simple test to verify the auto-whitelist logic.
"""

def test_whitelist_logic():
    print('Testing whitelist logic...')
    whitelist_was_none = True
    ambiguous_paths = ['models/test.mdl', 'sounds/test.wav']
    whitelist = set()
    if ambiguous_paths:
        print(f'Found {len(ambiguous_paths)} potentially ambiguous paths')
        if whitelist_was_none:
            print(f'Automatically adding {len(ambiguous_paths)} ambiguous paths to whitelist')
            whitelist.update(ambiguous_paths)
            print(f'Whitelist now contains: {whitelist}')
        else:
            print('Whitelist was provided, not auto-adding ambiguous paths')
    print('Test completed!')
if __name__ == '__main__':
    test_whitelist_logic()
