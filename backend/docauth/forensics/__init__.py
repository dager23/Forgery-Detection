"""Forensic analysis engine (independent of the web layer)."""

from docauth.forensics.engine import Engine, EngineReport
from docauth.forensics.loader import UnsupportedFile, load_document, load_template_image
from docauth.forensics.types import Document, TemplateRef

__all__ = [
    "Document",
    "Engine",
    "EngineReport",
    "TemplateRef",
    "UnsupportedFile",
    "load_document",
    "load_template_image",
]
