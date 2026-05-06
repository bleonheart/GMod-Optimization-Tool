"""
Utility module for tracking file removals across the application.
"""
import os
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple
from utils.formatting import format_size

class RemovalTracker:
    """Tracks files that have been removed during optimization operations."""

    def __init__(self):
        self.removals: List[Dict] = []
        self.removed_directories: List[str] = []

    def record_file_removal(self, file_path: str, operation: str, file_size: int=0, reason: str=''):
        """Record a file removal.
        
        Args:
            file_path: Path to the removed file (relative to content folder preferred)
            operation: Name of the operation that removed the file (e.g., "Remove game files", "Unused model formats")
            file_size: Size of the removed file in bytes
            reason: Optional reason for removal
        """
        self.removals.append({'file_path': file_path, 'operation': operation, 'file_size': file_size, 'reason': reason})

    def record_directory_removal(self, dir_path: str, operation: str, reason: str=''):
        """Record a directory removal.
        
        Args:
            dir_path: Path to the removed directory
            operation: Name of the operation that removed the directory
            reason: Optional reason for removal
        """
        self.removed_directories.append({'dir_path': dir_path, 'operation': operation, 'reason': reason})

    def get_summary(self) -> Dict:
        """Get a summary of all removals."""
        total_files = len(self.removals)
        total_size = sum((r['file_size'] for r in self.removals))
        total_dirs = len(self.removed_directories)
        by_operation = defaultdict(lambda: {'count': 0, 'size': 0, 'files': []})
        for removal in self.removals:
            op = removal['operation']
            by_operation[op]['count'] += 1
            by_operation[op]['size'] += removal['file_size']
            by_operation[op]['files'].append(removal['file_path'])
        return {'total_files': total_files, 'total_size': total_size, 'total_directories': total_dirs, 'by_operation': dict(by_operation)}

    def generate_markdown_report(self, output_path: str, content_folder: str=''):
        """Generate a markdown report of all removed files.
        
        Args:
            output_path: Path where the markdown report should be saved
            content_folder: Optional content folder path for relative path display
        """
        summary = self.get_summary()
        by_extension = defaultdict(lambda: {'count': 0, 'size': 0})
        file_sizes = []
        for removal in self.removals:
            file_path = removal['file_path']
            file_size = removal['file_size']
            file_sizes.append(file_size)
            _, ext = os.path.splitext(file_path)
            ext = ext.lower() if ext else '(no extension)'
            by_extension[ext]['count'] += 1
            by_extension[ext]['size'] += file_size
        size_stats = {}
        if file_sizes:
            file_sizes_sorted = sorted(file_sizes)
            size_stats = {'min': min(file_sizes), 'max': max(file_sizes), 'avg': sum(file_sizes) // len(file_sizes), 'median': file_sizes_sorted[len(file_sizes_sorted) // 2] if file_sizes_sorted else 0, 'total': sum(file_sizes)}
        top_files = sorted(self.removals, key=lambda x: x['file_size'], reverse=True)[:20]
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('# File Removal Report\n\n')
            f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            if content_folder:
                f.write(f'Content folder: `{content_folder}`\n\n')
            f.write('## Summary\n\n')
            f.write(f"- **Total files removed**: {summary['total_files']:,}\n")
            f.write(f"- **Total space saved**: {format_size(summary['total_size'])}\n")
            f.write(f"- **Total directories removed**: {summary['total_dirs']:,}\n\n")
            if size_stats:
                f.write('### File Size Statistics\n\n')
                f.write(f"- **Smallest file**: {format_size(size_stats['min'])}\n")
                f.write(f"- **Largest file**: {format_size(size_stats['max'])}\n")
                f.write(f"- **Average file size**: {format_size(size_stats['avg'])}\n")
                f.write(f"- **Median file size**: {format_size(size_stats['median'])}\n\n")
            if summary['by_operation']:
                f.write('## Removals by Operation\n\n')
                for operation, stats in sorted(summary['by_operation'].items(), key=lambda x: x[1]['size'], reverse=True):
                    percentage = stats['size'] / summary['total_size'] * 100 if summary['total_size'] > 0 else 0
                    f.write(f'### {operation}\n\n')
                    f.write(f"- **Files removed**: {stats['count']:,} ({stats['count'] / summary['total_files'] * 100:.1f}%)\n")
                    f.write(f"- **Space saved**: {format_size(stats['size'])} ({percentage:.1f}% of total)\n")
                    f.write(f"- **Average file size**: {(format_size(stats['size'] // stats['count']) if stats['count'] > 0 else '0 B')}\n\n")
            if by_extension:
                f.write('## Removals by File Type\n\n')
                f.write('| Extension | Files | Space Saved | % of Total | Avg Size |\n')
                f.write('|-----------|-------|-------------|------------|----------|\n')
                for ext, stats in sorted(by_extension.items(), key=lambda x: x[1]['size'], reverse=True):
                    percentage = stats['size'] / summary['total_size'] * 100 if summary['total_size'] > 0 else 0
                    avg_size = stats['size'] // stats['count'] if stats['count'] > 0 else 0
                    f.write(f"| `{ext}` | {stats['count']:,} | {format_size(stats['size'])} | {percentage:.1f}% | {format_size(avg_size)} |\n")
                f.write('\n')
            if top_files:
                f.write('## Top 20 Largest Files Removed\n\n')
                f.write('| Rank | File Path | Size | Operation |\n')
                f.write('|------|-----------|------|-----------|\n')
                for idx, removal in enumerate(top_files, 1):
                    file_path = removal['file_path']
                    display_path = file_path if len(file_path) <= 80 else '...' + file_path[-77:]
                    f.write(f"| {idx} | `{display_path}` | {format_size(removal['file_size'])} | {removal['operation']} |\n")
                f.write('\n')
            if summary['by_operation']:
                f.write('## Detailed Removals by Operation\n\n')
                for operation, stats in sorted(summary['by_operation'].items(), key=lambda x: x[1]['size'], reverse=True):
                    f.write(f'### {operation}\n\n')
                    f.write(f"- **Files removed**: {stats['count']:,}\n")
                    f.write(f"- **Space saved**: {format_size(stats['size'])}\n\n")
                    if stats['files']:
                        f.write('#### Removed Files\n\n')
                        if len(stats['files']) <= 50:
                            for file_path in sorted(stats['files']):
                                f.write(f'- `{file_path}`\n')
                        else:
                            for file_path in sorted(stats['files'])[:50]:
                                f.write(f'- `{file_path}`\n')
                            f.write(f"\n*... and {len(stats['files']) - 50} more files*\n")
                        f.write('\n')
            if self.removed_directories:
                f.write('## Removed Directories\n\n')
                dirs_by_op = defaultdict(list)
                for dir_info in self.removed_directories:
                    dirs_by_op[dir_info['operation']].append(dir_info)
                for operation, dirs in dirs_by_op.items():
                    f.write(f'### {operation} ({len(dirs)} directories)\n\n')
                    for dir_info in sorted(dirs, key=lambda x: x['dir_path']):
                        reason_text = f" - {dir_info['reason']}" if dir_info.get('reason') else ''
                        f.write(f"- `{dir_info['dir_path']}`{reason_text}\n")
                    f.write('\n')
            if not self.removals and (not self.removed_directories):
                f.write('No files or directories were removed.\n')
        print(f'📄 Removal report saved to: {output_path}')

    def clear(self):
        """Clear all tracked removals."""
        self.removals.clear()
        self.removed_directories.clear()
_global_tracker = RemovalTracker()

def get_tracker() -> RemovalTracker:
    """Get the global removal tracker instance."""
    return _global_tracker

def reset_tracker():
    """Reset the global removal tracker."""
    _global_tracker.clear()
