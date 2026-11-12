import secrets
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SIZE = 320  # stored avatars are SIZE x SIZE JPEGs


class AvatarError(ValueError):
    pass


def save_avatar(upload, user_id):
    """Validate an uploaded image, crop it to a centred square, resize, and
    store it as a fresh JPEG. Returns the path relative to MEDIA_ROOT.
    Re-encoding means only real pixels are kept (no scripts, no EXIF/GPS)."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise AvatarError("Image is too large (max 5 MB).")
    data = upload.read()
    try:
        Image.open(BytesIO(data)).verify()
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise AvatarError("That file is not an image we can read.")
    if img.width * img.height > 40_000_000:
        raise AvatarError("Image is too large.")
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (SIZE, SIZE), method=Image.LANCZOS)
    folder = settings.MEDIA_ROOT / "avatars"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{user_id}-{secrets.token_hex(8)}.jpg"
    img.save(folder / name, "JPEG", quality=86, optimize=True)
    return f"avatars/{name}"


def delete_old_avatar(url):
    """Remove a previous upload of ours (never touches outside avatars/)."""
    marker = settings.MEDIA_URL + "avatars/"
    if not url or marker not in url:
        return
    name = url.rsplit("/", 1)[-1]
    if "/" in name or "\\" in name or not name.endswith(".jpg"):
        return
    try:
        (settings.MEDIA_ROOT / "avatars" / name).unlink(missing_ok=True)
    except OSError:
        pass
