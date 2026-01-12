import argparse
import json
import mimetypes
import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
THUMB_SUFFIX = ".thumb.jpg"
THUMB_SIZE = 360
THUMB_QUALITY = 82
DISPLAY_SUFFIX = ".display.jpg"
DISPLAY_SIZE = 1600
DISPLAY_QUALITY = 88


def split_tags(value):
    return [t for t in (value or "").split() if t]


def safe_relative(root, target):
    root = root.resolve()
    target = target.resolve()
    try:
        return target.relative_to(root)
    except ValueError:
        return None


def to_file_url(rel_path):
    return "/files/" + quote(rel_path.as_posix())


def to_thumb_url(rel_path):
    return "/thumbs/" + quote(rel_path.as_posix() + THUMB_SUFFIX)


def make_thumb_path(root, rel_path):
    return root / ".thumbs" / (rel_path.as_posix() + THUMB_SUFFIX)


def to_display_url(rel_path):
    return "/display/" + quote(rel_path.as_posix() + DISPLAY_SUFFIX)


def make_display_path(root, rel_path):
    return root / ".display" / (rel_path.as_posix() + DISPLAY_SUFFIX)


def load_items(root, index_path=None, progress=None):
    items = []
    if index_path and index_path.exists():
        with index_path.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                img_path = Path(row.get("image_path", ""))
                if not img_path.is_absolute():
                    img_path = root / img_path
                rel = safe_relative(root, img_path)
                if not rel or not img_path.exists():
                    continue
                caption_path = Path(row.get("caption_path", ""))
                if not caption_path.is_absolute():
                    caption_path = root / caption_path
                caption = ""
                if caption_path.exists():
                    caption = caption_path.read_text(encoding="utf-8").strip()
                tags = {
                    "artist": row.get("artist", []),
                    "copyright": row.get("copyright", []),
                    "character": row.get("character", []),
                    "general": row.get("general", []),
                }
                items.append(
                    {
                        "name": img_path.name,
                        "image_url": to_file_url(rel),
                        "thumb_url": to_thumb_url(rel),
                        "display_url": to_display_url(rel),
                        "caption": caption,
                        "tags": tags,
                    }
                )
                if progress and idx % 500 == 0:
                    progress(idx)
        items.sort(key=lambda item: item["name"].lower())
        return items

    for idx, path in enumerate(root.rglob("*"), start=1):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = safe_relative(root, path)
        if not rel:
            continue
        caption_path = Path(f"{path}.caption.txt")
        caption = ""
        if caption_path.exists():
            caption = caption_path.read_text(encoding="utf-8").strip()
        json_path = Path(f"{path}.json")
        tags = {"artist": [], "copyright": [], "character": [], "general": []}
        if json_path.exists():
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
                tags["artist"] = split_tags(meta.get("tag_string_artist"))
                tags["copyright"] = split_tags(meta.get("tag_string_copyright"))
                tags["character"] = split_tags(meta.get("tag_string_character"))
                tags["general"] = split_tags(meta.get("tag_string_general"))
            except json.JSONDecodeError:
                pass
        items.append(
            {
                "name": path.name,
                "image_url": to_file_url(rel),
                "thumb_url": to_thumb_url(rel),
                "display_url": to_display_url(rel),
                "caption": caption,
                "tags": tags,
            }
        )
        if progress and idx % 500 == 0:
            progress(idx)
    items.sort(key=lambda item: item["name"].lower())
    return items


def build_resized(source_path, target_path, max_size, quality):
    if target_path.exists():
        return False
    if not PIL_AVAILABLE:
        return False

    try:
        image = Image.open(source_path)
        image = ImageOps.exif_transpose(image)
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS

        if image.mode in ("RGBA", "LA"):
            background = Image.new("RGB", image.size, (16, 16, 16))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        image.thumbnail((max_size, max_size), resample=resample)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(target_path, "JPEG", quality=quality, optimize=True)
        return True
    except Exception:
        return False


def prebuild_cache(root):
    if not PIL_AVAILABLE:
        print("Pillow not available. Install pillow to prebuild cache.")
        return
    total = 0
    built = 0
    for path in root.rglob("*"):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = safe_relative(root, path)
        if not rel:
            continue
        total += 1
        thumb_path = make_thumb_path(root, rel)
        display_path = make_display_path(root, rel)
        if build_resized(path, thumb_path, THUMB_SIZE, THUMB_QUALITY):
            built += 1
        if build_resized(path, display_path, DISPLAY_SIZE, DISPLAY_QUALITY):
            built += 1
        if total % 200 == 0:
            print(f"Prebuild progress: {total} images scanned")
    print(f"Prebuild done. Images: {total}, files created: {built}")


class ViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, root=None, store=None, **kwargs):
        self.viewer_root = Path(directory or ".")
        self.dataset_root = root
        self.store = store
        super().__init__(*args, directory=directory, **kwargs)

    def send_file(self, path, cache_seconds=0, content_type=None):
        if not path.exists():
            self.send_error(404, "Not Found")
            return
        ctype = content_type or mimetypes.guess_type(str(path))[0]
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        if cache_seconds:
            self.send_header("Cache-Control", f"public, max-age={cache_seconds}")
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/items":
            ready = bool(self.store.ready)
            payload = {
                "root": str(self.dataset_root),
                "ready": ready,
                "scanned": int(self.store.scanned),
                "items": self.store.items if ready else [],
            }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path.startswith("/thumbs/"):
            rel_thumb = unquote(parsed.path[len("/thumbs/") :])
            if not rel_thumb.endswith(THUMB_SUFFIX):
                self.send_error(404, "Not Found")
                return
            rel_src = rel_thumb[: -len(THUMB_SUFFIX)]
            src_path = (self.dataset_root / rel_src).resolve()
            if not safe_relative(self.dataset_root, src_path):
                self.send_error(403, "Forbidden")
                return
            if not src_path.exists():
                self.send_error(404, "Not Found")
                return
            rel_src_path = Path(rel_src)
            thumb_path = make_thumb_path(self.dataset_root, rel_src_path)
            build_resized(src_path, thumb_path, THUMB_SIZE, THUMB_QUALITY)
            if thumb_path.exists():
                self.send_file(thumb_path, cache_seconds=86400, content_type="image/jpeg")
                return
            self.send_file(src_path, cache_seconds=3600)
            return

        if parsed.path.startswith("/display/"):
            rel_disp = unquote(parsed.path[len("/display/") :])
            if not rel_disp.endswith(DISPLAY_SUFFIX):
                self.send_error(404, "Not Found")
                return
            rel_src = rel_disp[: -len(DISPLAY_SUFFIX)]
            src_path = (self.dataset_root / rel_src).resolve()
            if not safe_relative(self.dataset_root, src_path):
                self.send_error(403, "Forbidden")
                return
            if not src_path.exists():
                self.send_error(404, "Not Found")
                return
            rel_src_path = Path(rel_src)
            display_path = make_display_path(self.dataset_root, rel_src_path)
            build_resized(src_path, display_path, DISPLAY_SIZE, DISPLAY_QUALITY)
            if display_path.exists():
                self.send_file(display_path, cache_seconds=3600, content_type="image/jpeg")
                return
            self.send_file(src_path, cache_seconds=3600)
            return

        if parsed.path.startswith("/files/"):
            rel_path = unquote(parsed.path[len("/files/") :])
            target = (self.dataset_root / rel_path).resolve()
            if not safe_relative(self.dataset_root, target):
                self.send_error(403, "Forbidden")
                return
            self.send_file(target, cache_seconds=3600)
            return

        if parsed.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()


def main():
    global THUMB_SIZE, DISPLAY_SIZE, THUMB_QUALITY, DISPLAY_QUALITY
    parser = argparse.ArgumentParser(description="Colab image viewer server")
    parser.add_argument("--root", required=True, help="Dataset root path")
    parser.add_argument("--index", help="Optional JSONL index path")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--prebuild", action="store_true", help="Prebuild thumbnails and display cache")
    parser.add_argument("--thumb-size", type=int, default=THUMB_SIZE)
    parser.add_argument("--display-size", type=int, default=DISPLAY_SIZE)
    parser.add_argument("--thumb-quality", type=int, default=THUMB_QUALITY)
    parser.add_argument("--display-quality", type=int, default=DISPLAY_QUALITY)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Root path not found: {root}")

    THUMB_SIZE = max(128, int(args.thumb_size))
    DISPLAY_SIZE = max(640, int(args.display_size))
    THUMB_QUALITY = min(95, max(40, int(args.thumb_quality)))
    DISPLAY_QUALITY = min(95, max(40, int(args.display_quality)))

    index_path = Path(args.index).resolve() if args.index else None
    if index_path and not index_path.exists():
        index_path = None
    if index_path is None:
        default_index = root / "dataset_index_fixed.jsonl"
        if default_index.exists():
            index_path = default_index
    if index_path is None:
        parent_index = root.parent / "dataset_index_fixed.jsonl"
        if parent_index.exists():
            index_path = parent_index

    viewer_root = Path(__file__).parent.resolve()
    store = type("ItemStore", (), {"items": [], "ready": False, "scanned": 0})()

    def progress(scanned):
        store.scanned = scanned

    def build_items():
        if args.prebuild:
            prebuild_cache(root)
        items = load_items(root, index_path=index_path, progress=progress)
        store.items = items
        store.ready = True

    threading.Thread(target=build_items, daemon=True).start()

    handler = lambda *hargs, **hkwargs: ViewerHandler(
        *hargs, directory=str(viewer_root), root=root, store=store, **hkwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving viewer at http://127.0.0.1:{args.port}")
    print(f"Dataset root: {root}")
    server.serve_forever()


if __name__ == "__main__":
    mimetypes.init()
    main()
