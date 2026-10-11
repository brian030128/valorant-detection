"""Download and verify every public character-select bundle linked by the viewer."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import struct
import time
from urllib.parse import unquote, urljoin, urlparse

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "assets/source/kingdomarchives"
INDEX = "https://kingdomarchives.com/modelviewer/viper"


def fetch(url, page):
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": page}, timeout=(15, 90))
            response.raise_for_status()
            return response.content
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def glb_document(raw):
    assert len(raw) >= 20
    magic, version, length = struct.unpack_from("<4sII", raw)
    assert magic == b"glTF" and version == 2 and length == len(raw), "Invalid GLB header"
    size, kind = struct.unpack_from("<II", raw, 12)
    assert kind == 0x4E4F534A and size + 20 <= length
    document = json.loads(raw[20:20 + size])
    offset = 12
    while offset < length:
        chunk_size, _ = struct.unpack_from("<II", raw, offset)
        offset += 8 + chunk_size
    assert offset == length, "Truncated GLB chunk"
    return document


def resource_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from resource_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from resource_strings(child)
    elif isinstance(value, str) and re.search(r"\.(png|jpg|jpeg|webp|glb|gltf|bin|fbx|ktx2)(?:\?.*)?$", value, re.I):
        yield value


def process_character(character):
    page, name, thumbnail = character
    slug = urlparse(page).path.rsplit("/", 1)[-1]
    assert re.fullmatch(r"[a-z0-9_-]+", slug)
    directory = ROOT / slug
    directory.mkdir(parents=True, exist_ok=True)
    text = fetch(page, page).decode()
    match = re.search(r"const MODEL_JSON = JSON.parse\('(.+?)'\);", text)
    if not match:
        raise ValueError(f"No model configuration for {name}")
    config = json.loads(json.loads('"' + match.group(1) + '"'))
    (directory / "viewer_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    model_base = urljoin(page, config["Model"]["Path"])
    model_url = urljoin(model_base, config["Model"]["Name"])
    urls = {model_url, thumbnail}
    for value in resource_strings(config):
        urls.add(urljoin(page if "/" in value else model_base, value))
    old_path = directory / "manifest.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    known = {f["url"]: f for f in old.get("files", [])}
    files = []
    documents = {}
    used_paths = {}
    pending = sorted(urls)
    while pending:
        url = pending.pop(0)
        if url in {f["url"] for f in files}:
            continue
        parsed = urlparse(url)
        assert parsed.scheme == "https" and parsed.netloc == "kingdomarchives.com"
        if url.startswith(model_base):
            relative = unquote(url[len(model_base):].split("?")[0])
        else:
            relative = "textures/" + unquote(parsed.path.rsplit("/", 1)[-1])
        if relative in used_paths and used_paths[relative] != url:
            relative = "shared/" + hashlib.sha256(url.encode()).hexdigest()[:12] + "_" + Path(relative).name
        used_paths[relative] = url
        destination = (directory / relative).resolve()
        assert destination.is_relative_to(directory.resolve())
        raw = destination.read_bytes() if destination.exists() else None
        cached = known.get(url)
        if raw is None or not cached or hashlib.sha256(raw).hexdigest() != cached["sha256"]:
            raw = fetch(url, page)
        extension = destination.suffix.lower()
        if extension == ".glb":
            document = glb_document(raw)
            documents[relative] = document
            for kind in ("buffers", "images"):
                for dependency in document.get(kind, []):
                    uri = dependency.get("uri", "")
                    if uri and not uri.startswith("data:"):
                        pending.append(urljoin(url, uri))
        elif extension in (".png", ".jpg", ".jpeg", ".webp"):
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".download")
        temporary.write_bytes(raw)
        temporary.replace(destination)
        files.append({"url": url, "file": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    primary = documents[config["Model"]["Name"]]
    (directory / "gltf_metadata.json").write_text(json.dumps(primary, indent=2), encoding="utf-8")
    manifest = {
        "name": name, "slug": slug, "source_page": page,
        "verified_at": datetime.now(timezone.utc).isoformat(), "files": files,
        "meshes": len(primary.get("meshes", [])), "skins": len(primary.get("skins", [])),
        "joints_per_skin": [len(s.get("joints", [])) for s in primary.get("skins", [])],
        "animations": [a.get("name") for a in primary.get("animations", [])],
        "head_nodes": [n.get("name") for n in primary.get("nodes", []) if "head" in n.get("name", "").lower()],
        "materials": [m.get("name") for m in primary.get("materials", [])],
        "extensions_required": primary.get("extensionsRequired", []),
        "note": "Character-select assets; viewer-specific materials are recorded in viewer_config.json. Download does not grant a reuse license. Assets owned by Riot Games.",
    }
    old_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"name": name, "slug": slug, "manifest": f"{slug}/manifest.json", "files": len(files),
            "bytes": sum(f["bytes"] for f in files), "animations": len(manifest["animations"]),
            "has_head_node": bool(manifest["head_nodes"])}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    text = fetch(INDEX, INDEX).decode()
    section = text.split("Agents - Character Select", 1)[1].split("Agents - First Person", 1)[0]
    entries = re.findall(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', section, re.S)
    characters = []
    for href, content in entries:
        name = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", content, re.S)
        thumbnail = re.search(r'<img[^>]+src="([^"]+)"', content)
        if name and thumbnail:
            characters.append((urljoin(INDEX, href), html.unescape(name.group(1).strip()), urljoin(INDEX, thumbnail.group(1))))
    assert characters and len({c[0] for c in characters}) == len(characters)
    print(f"Discovered {len(characters)} characters", flush=True)
    catalog = {"source": INDEX, "scope": "Agents - Character Select", "expected_characters": len(characters), "characters": [], "errors": []}
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs = {executor.submit(process_character, c): c for c in characters}
        for job in as_completed(jobs):
            character = jobs[job]
            try:
                result = job.result()
                catalog["characters"].append(result)
                print(f"OK {result['name']}: {result['files']} files, {result['bytes']/1e6:.1f} MB, {result['animations']} animations", flush=True)
            except Exception as error:
                catalog["errors"].append({"name": character[1], "page": character[0], "error": str(error)})
                print(f"FAILED {character[1]}: {error}", flush=True)
            catalog["characters"].sort(key=lambda c: c["slug"])
            (ROOT / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"Complete: {len(catalog['characters'])}/{len(characters)} characters, {sum(c['bytes'] for c in catalog['characters'])/1e6:.1f} MB", flush=True)
    if catalog["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
