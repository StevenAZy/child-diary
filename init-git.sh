#!/bin/bash
# Initialize Git repository and make first commit

set -e

echo "🍑 Initializing Git repository..."

# Initialize git if not already done
if [ ! -d ".git" ]; then
    git init
    echo "✓ Git repository initialized"
fi

# Add all files (respecting .gitignore)
echo "Adding files..."
git add .

# Show what will be committed
echo ""
echo "Files to be committed:"
git status

echo ""
echo "Ignored files:"
git status --ignored | grep -A 100 "Ignored files:" | tail -n +2

echo ""
read -p "Do you want to commit these files? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git commit -m "Initial commit: Child Growth Diary"
    echo ""
    echo "✓ Initial commit created"
    echo ""
    echo "Next steps:"
    echo "  1. Create a repository on GitHub"
    echo "  2. Add remote: git remote add origin https://github.com/yourusername/child-diary.git"
    echo "  3. Push: git push -u origin master"
else
    echo "Commit cancelled"
fi
