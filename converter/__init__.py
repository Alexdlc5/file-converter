"""File Converter: turn documents, images, video, audio, spreadsheets and more
into other formats, entirely on this computer."""

from .engine import QUALITIES, convert, converters, hint_for, targets_for
from .tools import Cancelled, ConversionError

__all__ = ["QUALITIES", "convert", "converters", "hint_for", "targets_for", "Cancelled",
           "ConversionError"]

__version__ = "1.0.0"
