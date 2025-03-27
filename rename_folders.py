#!/usr/bin/env python3
import os
import unicodedata
import re

def slugify(value):
    """
    Convert to ASCII, convert spaces to underscores, remove characters that
    aren't alphanumerics, underscores, or hyphens, convert to lowercase,
    and strip leading and trailing whitespace.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '_', value)

def rename_folders(directory, recursive=True):
    """Rename all folders in the given directory to remove spaces and special characters."""
    try:
        items = os.listdir(directory)
    except Exception as e:
        print(f"Error accessing {directory}: {e}")
        return

    # First pass: rename current level folders
    for item in items:
        path = os.path.join(directory, item)
        if os.path.isdir(path):
            new_name = slugify(item)
            if new_name and new_name != item.lower():
                new_path = os.path.join(directory, new_name)
                try:
                    os.rename(path, new_path)
                    print(f"Renamed: {path} -> {new_path}")
                    # Update path for recursive call
                    path = new_path
                except Exception as e:
                    print(f"Error renaming {path}: {e}")
            
            # Recursively rename subdirectories
            if recursive:
                rename_folders(path, recursive)

if __name__ == "__main__":
    rename_folders("arquivos")
    print("Renomeação concluída!")
