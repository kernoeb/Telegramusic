import os
import re

from mutagen.flac import FLAC
from mutagen.mp3 import MP3


def clean_filename(filename):
    """
    Cleans a string to be suitable for use as a filename or directory name.
    Removes or replaces potentially problematic characters.
    """
    # Replace potentially problematic characters with underscores
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", filename)
    # Remove leading/trailing whitespace and dots
    cleaned = cleaned.strip(" .")
    # Replace consecutive underscores with a single underscore
    cleaned = re.sub(r"_+", "_", cleaned)
    # Ensure the filename is not empty after cleaning
    if not cleaned:
        return "_"
    return cleaned


def get_audio_duration(file_path):
    """Get the duration of the audio file."""
    try:
        extension = os.path.splitext(file_path)[1].lower()
        if extension == ".mp3":
            audio = MP3(file_path)
            return int(audio.info.length)
        elif extension == ".flac":
            audio = FLAC(file_path)
            return int(audio.info.length)
        else:
            print(
                f"Warning: Unsupported audio format for duration calculation: {extension}"
            )
            return 0  # Unknown duration
    except Exception as e:
        print(f"Error getting audio duration for {file_path}: {e}")
        return 0
