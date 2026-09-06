"""Photo proof processing (#19): resize to a configured max dimension
and strip EXIF before the image is ever written to storage. Re-encoding
through Pillow (loading pixel data into a fresh image with no `info`
dict) is what strips the EXIF — there is no separate "remove EXIF"
step.

Storage itself is plain Django FileSystemStorage (MEDIA_ROOT) for now.
Swapping in an S3-compatible backend via django-storages depends on
#38 (post-MVP, env-driven AWS_* settings) landing first; this module
does not know or care which storage backend is configured.
"""

import io

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image


def process_photo_proof(uploaded_file):
    """Return a new Django File: `uploaded_file` resized so its longest
    side is at most PHOTO_PROOF_MAX_DIMENSION, re-encoded as JPEG with
    no EXIF. Leaves the original upload argument untouched.
    """
    max_dimension = getattr(settings, 'PHOTO_PROOF_MAX_DIMENSION', 1600)
    image = Image.open(uploaded_file)
    image = image.convert('RGB')
    image.thumbnail((max_dimension, max_dimension))

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG')
    buffer.seek(0)

    name = uploaded_file.name.rsplit('.', 1)[0] + '.jpg'
    return InMemoryUploadedFile(
        buffer, None, name, 'image/jpeg', buffer.getbuffer().nbytes, None
    )
