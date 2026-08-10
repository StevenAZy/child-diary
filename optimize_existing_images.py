#!/usr/bin/env python3
"""
Script to optimize existing images in the uploads directory.
Compresses images and generates thumbnails for faster loading.
"""

import os
import sys
import sqlite3
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, compress_image, generate_thumbnail, HAS_PIL

def optimize_existing_images():
    """Optimize all existing images in the uploads directory."""
    if not HAS_PIL:
        print("Error: PIL/Pillow not available. Cannot optimize images.")
        return False
    
    uploads_dir = app.config['UPLOAD_FOLDER']
    db_path = app.config['DATABASE']
    
    print("=" * 60)
    print("Image Optimization Script")
    print("=" * 60)
    print(f"Uploads directory: {uploads_dir}")
    print(f"Database: {db_path}")
    print()
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all image media entries
    cursor.execute("SELECT id, entry_id, filepath, media_type FROM media WHERE media_type = 'image'")
    images = cursor.fetchall()
    
    print(f"Found {len(images)} images to optimize")
    print()
    
    optimized_count = 0
    thumb_count = 0
    total_saved = 0
    
    for img in images:
        img_id = img['id']
        entry_id = img['entry_id']
        filepath = img['filepath']
        
        # Full path to image
        full_path = os.path.join(uploads_dir, filepath)
        
        if not os.path.exists(full_path):
            print(f"  ⚠ Skipping {filepath} (file not found)")
            continue
        
        # Get original size
        original_size = os.path.getsize(full_path)
        
        # Get file extension
        ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
        
        if ext not in {'jpg', 'jpeg', 'png', 'gif'}:
            print(f"  ⚠ Skipping {filepath} (unsupported format: {ext})")
            continue
        
        print(f"  Processing: {filepath} ({original_size / 1024:.1f} KB)")
        
        # Compress image
        try:
            compress_image(full_path, max_size=1200, quality=80)
            new_size = os.path.getsize(full_path)
            saved = original_size - new_size
            total_saved += saved
            
            if saved > 0:
                print(f"    ✓ Compressed: {original_size / 1024:.1f} KB -> {new_size / 1024:.1f} KB (saved {saved / 1024:.1f} KB)")
                optimized_count += 1
            else:
                print(f"    - Already optimized")
        except Exception as e:
            print(f"    ✗ Compression failed: {e}")
        
        # Generate thumbnail if not exists
        thumb_path = full_path.rsplit('.', 1)[0] + '_thumb.jpg'
        if not os.path.exists(thumb_path):
            try:
                generate_thumbnail(full_path, thumb_path, size=400)
                if os.path.exists(thumb_path):
                    # Update database with thumbnail path
                    thumb_rel = filepath.rsplit('.', 1)[0] + '_thumb.jpg'
                    cursor.execute("UPDATE media SET poster = ? WHERE id = ?", (thumb_rel, img_id))
                    print(f"    ✓ Generated thumbnail: {os.path.basename(thumb_path)}")
                    thumb_count += 1
            except Exception as e:
                print(f"    ✗ Thumbnail generation failed: {e}")
        else:
            # Update database if poster is empty
            cursor.execute("SELECT poster FROM media WHERE id = ?", (img_id,))
            result = cursor.fetchone()
            if not result['poster']:
                thumb_rel = filepath.rsplit('.', 1)[0] + '_thumb.jpg'
                cursor.execute("UPDATE media SET poster = ? WHERE id = ?", (thumb_rel, img_id))
                print(f"    ✓ Updated database with existing thumbnail")
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print()
    print("=" * 60)
    print("Optimization Complete")
    print("=" * 60)
    print(f"Images processed: {len(images)}")
    print(f"Images optimized: {optimized_count}")
    print(f"Thumbnails generated: {thumb_count}")
    print(f"Total space saved: {total_saved / 1024:.1f} KB ({total_saved / (1024*1024):.2f} MB)")
    print()
    
    return True

if __name__ == '__main__':
    with app.app_context():
        optimize_existing_images()
