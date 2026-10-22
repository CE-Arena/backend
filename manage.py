#!/usr/bin/env python3
"""CE ARENA management commands. Production configuration stays outside the site."""
import os
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        os.environ["CE_ARENA_TESTING"] = "1"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "arena_project.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
