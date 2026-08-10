#!/bin/bash
# Setup script for Child Diary

set -e

echo "🍑 小宝的成长日记 - Setup Script"
echo "=================================="

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Create .env file if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    
    # Generate secret key
    secret_key=$(python3 -c "import os; print(os.urandom(32).hex())")
    sed -i "s/your-secret-key-here/$secret_key/" .env
    
    echo "✓ .env file created"
    echo ""
    echo "⚠️  Please edit .env and set your ADMIN_PASSWORD_HASH"
    echo "   Generate hash with: python3 -c \"from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))\""
fi

# Create uploads directory
mkdir -p uploads
echo "✓ Uploads directory created"

# Initialize database
echo "Initializing database..."
python3 -c "from app import app, init_db; 
with app.app_context():
    init_db()
print('✓ Database initialized')"

echo ""
echo "🎉 Setup complete!"
echo ""
echo "To start the application:"
echo "  source venv/bin/activate"
echo "  python3 app.py"
echo ""
echo "Then visit: http://localhost:5000"
