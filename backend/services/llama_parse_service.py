"""
LlamaParse service — parses documents into clean markdown text.

Handles all document types the frontend accepts:
  - Documents:  PDF, DOCX, DOC, TXT, RTF, ODT
  - Images:     PNG, JPG, JPEG, TIFF, HEIC, BMP
  - Audio:      MP3, MP4, M4A, WAV, WEBM, OGG

LlamaParse converts each of these to clean markdown that GPT-4o can then
analyse for summary, prescriptions, appointments, and referrals.

If the file extension is not in SUPPORTED_EXTENSIONS, a ValueError is raised
with a friendly human-readable message — the endpoint converts this to a 422
so the frontend can display it instead of a generic error.
"""

import os
import tempfile
from pathlib import Path

from config import get_settings

settings = get_settings()

# Extensions LlamaParse can handle
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    # Documents
    ".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt",
    # Images (OCR via LlamaParse's vision pipeline)
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic", ".bmp",
    # Audio (transcribed then parsed)
    ".mp3", ".mp4", ".m4a", ".wav", ".webm", ".ogg",
})

UNSUPPORTED_FILE_MESSAGE = (
    "That file type isn't supported. Please upload one of these formats:\n\n"
    "• Documents: PDF, Word (DOCX), plain text (TXT)\n"
    "• Images: PNG, JPG, TIFF, HEIC\n"
    "• Audio recordings: MP3, MP4, M4A, WAV"
)


async def parse_document(file_bytes: bytes, filename: str) -> str:
    """
    Parse *any* supported document into clean markdown text via LlamaParse.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename including extension — used to determine parser pipeline.

    Returns:
        Markdown string suitable for downstream GPT-4o analysis.

    Raises:
        ValueError:   File extension not in SUPPORTED_EXTENSIONS.
        RuntimeError: LLAMA_CLOUD_API_KEY not configured, or parsing failed.
    """
    ext = Path(filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(UNSUPPORTED_FILE_MESSAGE)

    if not settings.llama_cloud_api_key:
        raise RuntimeError(
            "LLAMA_CLOUD_API_KEY is not configured. "
            "Add it to your .env file to enable document parsing."
        )

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from llama_parse import LlamaParse, ResultType  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "llama-parse is not installed. Run: pip install llama-parse==0.6.9"
        ) from exc

    # LlamaParse determines file type from the extension, so we write to a named
    # temp file that preserves the original extension. aload_data also accepts raw
    # bytes but does not infer file type from content — the extension is required.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        parser = LlamaParse(
            api_key=settings.llama_cloud_api_key,
            result_type=ResultType.MD,
            verbose=False,
            show_progress=False,
        )

        documents = await parser.aload_data(tmp_path)

        if not documents:
            raise RuntimeError("LlamaParse returned no content from the document.")

        markdown = "\n\n".join(doc.text for doc in documents).strip()

        if not markdown:
            raise RuntimeError("LlamaParse extracted empty text from the document.")

        return markdown

    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError(f"Document parsing failed: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
