#!/usr/bin/env python3
"""
Automated backup script for Child Diary application.
Backs up database, uploads, templates, and static files.
"""

import os
import sys
import shutil
import sqlite3
import gzip
import json
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
DB_FILE = os.path.join(BASE_DIR, 'diary.db')
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
KEEP_BACKUPS = 30  # Keep last 30 backups

def create_backup_dir():
    """Create backup directory if it doesn't exist."""
    os.makedirs(BACKUP_DIR, exist_ok=True)

def get_backup_filename():
    """Generate backup filename with timestamp."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f'child_diary_backup_{timestamp}'

def backup_database(backup_path):
    """Backup SQLite database with compression."""
    if not os.path.exists(DB_FILE):
        print(f"Warning: Database file not found: {DB_FILE}")
        return False
    
    db_backup_path = os.path.join(backup_path, 'diary.db.gz')
    
    try:
        # Use SQLite backup API for consistent backup
        conn = sqlite3.connect(DB_FILE)
        backup_conn = sqlite3.connect(':memory:')
        conn.backup(backup_conn)
        
        # Write to compressed file
        with gzip.open(db_backup_path, 'wb') as f:
            # Dump as SQL
            for line in backup_conn.iterdump():
                f.write((line + '\n').encode('utf-8'))
        
        backup_conn.close()
        conn.close()
        
        print(f"✓ Database backed up: {db_backup_path}")
        return True
    except Exception as e:
        print(f"✗ Database backup failed: {e}")
        return False

def backup_directory(src_dir, backup_path, dir_name):
    """Backup a directory with compression."""
    if not os.path.exists(src_dir):
        print(f"Warning: Directory not found: {src_dir}")
        return False
    
    dest_dir = os.path.join(backup_path, dir_name)
    
    try:
        shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
        print(f"✓ {dir_name} backed up: {dest_dir}")
        return True
    except Exception as e:
        print(f"✗ {dir_name} backup failed: {e}")
        return False

def backup_metadata(backup_path):
    """Backup application metadata and statistics."""
    metadata = {
        'backup_date': datetime.now().isoformat(),
        'backup_version': '1.0',
        'files': {}
    }
    
    # Count files in uploads
    if os.path.exists(UPLOADS_DIR):
        total_files = 0
        total_size = 0
        for root, dirs, files in os.walk(UPLOADS_DIR):
            for f in files:
                filepath = os.path.join(root, f)
                total_files += 1
                total_size += os.path.getsize(filepath)
        
        metadata['uploads'] = {
            'total_files': total_files,
            'total_size_mb': round(total_size / (1024 * 1024), 2)
        }
    
    # Database statistics
    if os.path.exists(DB_FILE):
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM entries")
            entry_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM media")
            media_count = cursor.fetchone()[0]
            
            conn.close()
            
            metadata['database'] = {
                'entries': entry_count,
                'media_files': media_count
            }
        except Exception as e:
            metadata['database'] = {'error': str(e)}
    
    # Write metadata
    metadata_file = os.path.join(backup_path, 'backup_metadata.json')
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Metadata backed up: {metadata_file}")
    return True

def cleanup_old_backups():
    """Remove old backups beyond retention period."""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = []
    for item in os.listdir(BACKUP_DIR):
        item_path = os.path.join(BACKUP_DIR, item)
        if os.path.isdir(item_path) and item.startswith('child_diary_backup_'):
            backups.append((item, item_path))
    
    # Sort by name (timestamp)
    backups.sort(reverse=True)
    
    # Remove old backups
    for i, (name, path) in enumerate(backups):
        if i >= KEEP_BACKUPS:
            try:
                shutil.rmtree(path)
                print(f"✓ Removed old backup: {name}")
            except Exception as e:
                print(f"✗ Failed to remove {name}: {e}")

def create_backup_archive(backup_path):
    """Create a compressed archive of the backup."""
    archive_name = f"{backup_path}.tar.gz"
    
    try:
        # Create tar.gz archive
        shutil.make_archive(
            backup_path,
            'gztar',
            os.path.dirname(backup_path),
            os.path.basename(backup_path)
        )
        
        # Remove the uncompressed directory
        shutil.rmtree(backup_path)
        
        # Get archive size
        size_mb = os.path.getsize(archive_name) / (1024 * 1024)
        print(f"✓ Backup archive created: {archive_name} ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        print(f"✗ Archive creation failed: {e}")
        return False

def main():
    """Main backup function."""
    print("=" * 50)
    print("Child Diary Backup Script")
    print("=" * 50)
    print(f"Backup directory: {BACKUP_DIR}")
    print()
    
    # Create backup directory
    create_backup_dir()
    
    # Generate backup path
    backup_name = get_backup_filename()
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    os.makedirs(backup_path, exist_ok=True)
    
    print(f"Creating backup: {backup_name}")
    print()
    
    # Perform backups
    success_count = 0
    total_tasks = 4
    
    if backup_database(backup_path):
        success_count += 1
    
    if backup_directory(UPLOADS_DIR, backup_path, 'uploads'):
        success_count += 1
    
    if backup_directory(TEMPLATES_DIR, backup_path, 'templates'):
        success_count += 1
    
    if backup_directory(STATIC_DIR, backup_path, 'static'):
        success_count += 1
    
    # Always backup metadata
    backup_metadata(backup_path)
    success_count += 1
    
    print()
    print(f"Backup tasks completed: {success_count}/{total_tasks + 1}")
    
    # Create archive
    print()
    if create_backup_archive(backup_path):
        print("✓ Backup completed successfully!")
    else:
        print("✗ Backup completed with warnings")
    
    # Cleanup old backups
    print()
    print("Cleaning up old backups...")
    cleanup_old_backups()
    
    print()
    print("=" * 50)
    print("Backup process finished")
    print("=" * 50)
    
    return 0 if success_count == total_tasks + 1 else 1

if __name__ == '__main__':
    sys.exit(main())
