#!/usr/bin/env python3
"""
Unit tests for Child Diary application.
Run with: python -m pytest test_app.py -v
"""

import os
import sys
import json
import sqlite3
import tempfile
import shutil
from datetime import datetime
from unittest import TestCase, main as unittest_main

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, init_db, get_db, sanitize_content, validate_file_content, allowed_file

class TestConfig:
    """Test configuration."""
    TESTING = True
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing
    SECRET_KEY = 'test-secret-key'

class BaseTestCase(TestCase):
    """Base test case with setup and teardown."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.upload_dir = tempfile.mkdtemp()
        
        # Configure app for testing
        app.config['DATABASE'] = self.db_path
        app.config['UPLOAD_FOLDER'] = self.upload_dir
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        
        # Initialize database
        init_db()
        
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        """Clean up test fixtures."""
        self.app_context.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        shutil.rmtree(self.upload_dir)
    
    def login(self, password='your-password'):
        """Helper to login."""
        # First get a CSRF token
        with self.app.session_transaction() as sess:
            sess['csrf_token'] = 'test-csrf-token'
        return self.app.post('/login', data={
            'password': password,
            'csrf_token': 'test-csrf-token'
        }, follow_redirects=True)
    
    def create_entry(self, title='Test Entry', content='Test content', entry_date='2024-01-01'):
        """Helper to create a diary entry."""
        return self.app.post('/api/entries', data={
            'title': title,
            'content': content,
            'entry_date': entry_date,
            'csrf_token': 'test-csrf-token'
        }, content_type='multipart/form-data')

class TestSanitization(BaseTestCase):
    """Test content sanitization."""
    
    def test_sanitize_script_tags(self):
        """Test that script tags are removed."""
        malicious = '<script>alert("xss")</script>Hello'
        result = sanitize_content(malicious)
        self.assertNotIn('<script>', result)
        self.assertIn('Hello', result)
    
    def test_sanitize_event_handlers(self):
        """Test that event handlers are removed."""
        malicious = '<img src="x" onerror="alert(1)">'
        result = sanitize_content(malicious)
        self.assertNotIn('onerror', result)
    
    def test_sanitize_safe_content(self):
        """Test that safe content is preserved."""
        safe = '<b>Bold</b> and <i>italic</i> text'
        result = sanitize_content(safe)
        self.assertIn('<b>', result)
        self.assertIn('<i>', result)

class TestFileValidation(BaseTestCase):
    """Test file validation."""
    
    def test_validate_png(self):
        """Test PNG file validation."""
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 24
        self.assertTrue(validate_file_content(png_header, 'png'))
    
    def test_validate_jpg(self):
        """Test JPEG file validation."""
        jpg_header = b'\xff\xd8\xff' + b'\x00' * 29
        self.assertTrue(validate_file_content(jpg_header, 'jpg'))
    
    def test_validate_gif(self):
        """Test GIF file validation."""
        gif_header = b'GIF89a' + b'\x00' * 26
        self.assertTrue(validate_file_content(gif_header, 'gif'))
    
    def test_validate_invalid_png(self):
        """Test invalid PNG detection."""
        fake_png = b'NOT_A_PNG' + b'\x00' * 23
        self.assertFalse(validate_file_content(fake_png, 'png'))
    
    def test_allowed_file(self):
        """Test allowed file extensions."""
        self.assertTrue(allowed_file('photo.jpg'))
        self.assertTrue(allowed_file('video.mp4'))
        self.assertFalse(allowed_file('script.exe'))
        self.assertFalse(allowed_file('noextension'))

class TestRoutes(BaseTestCase):
    """Test application routes."""
    
    def test_index_page(self):
        """Test index page loads."""
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('小宝的成长日记', response.data.decode())
    
    def test_login_page(self):
        """Test login page loads."""
        response = self.app.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('管理密码', response.data.decode())
    
    def test_admin_requires_login(self):
        """Test admin page requires authentication."""
        response = self.app.get('/admin')
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_login_success(self):
        """Test successful login."""
        response = self.login('your-password')
        self.assertEqual(response.status_code, 200)
        self.assertIn('写日记', response.data.decode())
    
    def test_login_failure(self):
        """Test failed login."""
        response = self.login('wrong_password')
        self.assertEqual(response.status_code, 200)
        self.assertIn('密码错误', response.data.decode())

class TestAPI(BaseTestCase):
    """Test API endpoints."""
    
    def test_create_entry_requires_auth(self):
        """Test that creating entry requires authentication."""
        response = self.create_entry()
        self.assertEqual(response.status_code, 401)
    
    def test_create_entry(self):
        """Test creating a diary entry."""
        self.login()
        response = self.create_entry()
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertIn('id', data)
    
    def test_create_entry_validation(self):
        """Test entry creation validation."""
        self.login()
        
        # Missing title
        response = self.app.post('/api/entries', data={
            'content': 'Test content',
            'entry_date': '2024-01-01',
            'csrf_token': 'test-csrf-token'
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)
        
        # Invalid date
        response = self.app.post('/api/entries', data={
            'title': 'Test',
            'content': 'Test content',
            'entry_date': 'invalid-date',
            'csrf_token': 'test-csrf-token'
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 400)
    
    def test_update_entry(self):
        """Test updating a diary entry."""
        self.login()
        
        # Create entry
        response = self.create_entry()
        entry_id = json.loads(response.data)['id']
        
        # Update entry
        response = self.app.put(f'/api/entries/{entry_id}',
            data=json.dumps({
                'title': 'Updated Title',
                'content': 'Updated content',
                'entry_date': '2024-01-02',
                'csrf_token': 'test-csrf-token'
            }),
            content_type='application/json')
        
        data = json.loads(response.data)
        self.assertTrue(data['success'])
    
    def test_delete_entry(self):
        """Test deleting a diary entry."""
        self.login()
        
        # Create entry
        response = self.create_entry()
        entry_id = json.loads(response.data)['id']
        
        # Delete entry
        response = self.app.delete(f'/api/entries/{entry_id}',
            data=json.dumps({'csrf_token': 'test-csrf-token'}),
            content_type='application/json')
        data = json.loads(response.data)
        self.assertTrue(data['success'])

class TestPagination(BaseTestCase):
    """Test pagination functionality."""
    
    def test_pagination(self):
        """Test that pagination works."""
        self.login()
        
        # Create multiple entries
        for i in range(25):
            self.create_entry(
                title=f'Entry {i}',
                content=f'Content {i}',
                entry_date=f'2024-01-{i+1:02d}'
            )
        
        # Test first page
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Entry', response.data.decode())
        
        # Test pagination parameters
        response = self.app.get('/?page=2&per_page=10')
        self.assertEqual(response.status_code, 200)

class TestSecurityHeaders(BaseTestCase):
    """Test security headers."""
    
    def test_security_headers(self):
        """Test that security headers are present."""
        response = self.app.get('/')
        
        self.assertIn('X-Content-Type-Options', response.headers)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        
        self.assertIn('X-Frame-Options', response.headers)
        self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')
        
        self.assertIn('Content-Security-Policy', response.headers)

class TestDatabase(BaseTestCase):
    """Test database operations."""
    
    def test_database_initialization(self):
        """Test database tables are created."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        self.assertIn('entries', tables)
        self.assertIn('media', tables)
        
        conn.close()
    
    def test_database_indexes(self):
        """Test database indexes are created."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        
        self.assertIn('idx_entries_entry_date', indexes)
        self.assertIn('idx_media_entry_id', indexes)
        
        conn.close()

if __name__ == '__main__':
    unittest_main()
