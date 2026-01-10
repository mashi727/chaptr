#!/usr/bin/env python3
"""
PyInstaller entry point for Video Chapter Editor.

This script provides a non-relative import entry point for PyInstaller.
"""

import sys
from pathlib import Path

# Ensure the package directory is in the path
package_dir = Path(__file__).parent
if str(package_dir) not in sys.path:
    sys.path.insert(0, str(package_dir))

# Import and run the main function
from media_scribe_workflow.ui.app import main

if __name__ == "__main__":
    main()
