import argparse
import json
import mimetypes
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


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


def load_items(root, index_path=None):
    items = []
    if index_path and index_path.exists():
        with index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
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
                        "caption": caption,
                        "tags": tags,
                    }
                )
        items.sort(key=lambda item: item["name"].lower())
        return items

    for path in root.rglob("*"):
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
                "caption": caption,
                "tags": tags,
            }
        )
    items.sort(key=lambda item: item["name"].lower())
    return items


class ViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, root=None, items=None, **kwargs):
        self.viewer_root = Path(directory or ".")
        self.dataset_root = root
        self.items = items or []
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/items":
            payload = {"root": str(self.dataset_root), "items": self.items}
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path.startswith("/files/"):
            rel_path = unquote(parsed.path[len("/files/") :])
            target = (self.dataset_root / rel_path).resolve()
            if not safe_relative(self.dataset_root, target):
                self.send_error(403, "Forbidden")
                return
            if not target.exists():
                self.send_error(404, "Not Found")
                return
            ctype, _ = mimetypes.guess_type(str(target))
            self.send_response(200)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            with target.open("rb") as handle:
                self.wfile.write(handle.read())
            return

        if parsed.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()


def main():
    parser = argparse.ArgumentParser(description="Local image viewer server")
    parser.add_argument("--root", required=True, help="Dataset root path")
    parser.add_argument("--index", help="Optional JSONL index path")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Root path not found: {root}")

    index_path = Path(args.index).resolve() if args.index else None
    if index_path and not index_path.exists():
        index_path = None
    if index_path is None:
        default_index = root / "dataset_index_fixed.jsonl"
        if default_index.exists():
            index_path = default_index

    items = load_items(root, index_path=index_path)

    viewer_root = Path(__file__).parent.resolve()
    handler = lambda *hargs, **hkwargs: ViewerHandler(
        *hargs, directory=str(viewer_root), root=root, items=items, **hkwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Serving viewer at http://127.0.0.1:{args.port}")
    print(f"Dataset root: {root}")
    server.serve_forever()


if __name__ == "__main__":
    mimetypes.init()
    main()
