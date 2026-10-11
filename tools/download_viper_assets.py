"""Download the public Viper model and textures referenced by Kingdom Archives."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import urljoin

import requests
from PIL import Image

PAGE = "https://kingdomarchives.com/modelviewer/viper"
ROOT = Path(__file__).resolve().parents[1] / "assets/source/kingdomarchives/viper"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": PAGE}


def download(item):
    url, relative = item
    destination = ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, headers=HEADERS, timeout=90)
    response.raise_for_status()
    content = response.content
    if relative.endswith(".png"):
        import io
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
    elif relative.endswith(".glb"):
        assert content[:4] == b"glTF", "Response is not a GLB"
    destination.write_bytes(content)
    return {"url": url, "file": relative, "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    response = requests.get(PAGE, headers=HEADERS, timeout=30)
    response.raise_for_status()
    match = re.search(r"const MODEL_JSON = JSON.parse\('(.+?)'\);", response.text)
    if not match:
        raise RuntimeError("Viewer model configuration not found")
    config = json.loads(json.loads('"' + match.group(1) + '"'))
    (ROOT / "viewer_config.json").write_text(json.dumps(config, indent=2))
    model = config["Model"]
    files = [(urljoin(PAGE, model["Path"] + model["Name"]), model["Name"])]
    for material in config["Materials"]:
        for key in ("DF", "ORM", "EM", "NM"):
            if key in material:
                value = material[key]
                files.append((urljoin(PAGE, value), "textures/" + value.rsplit("/", 1)[-1]))
    files = list(dict.fromkeys(files))
    with ThreadPoolExecutor(max_workers=4) as executor:
        downloaded = list(executor.map(download, files))
    raw = (ROOT / model["Name"]).read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    assert magic == b"glTF" and version == 2 and length == len(raw)
    json_length, chunk_type = struct.unpack_from("<II", raw, 12)
    assert chunk_type == 0x4E4F534A
    document = json.loads(raw[20:20 + json_length])
    (ROOT / "gltf_metadata.json").write_text(json.dumps(document, indent=2))
    manifest = {
        "source_page": PAGE,
        "files": downloaded,
        "meshes": len(document.get("meshes", [])),
        "skins": len(document.get("skins", [])),
        "joints_per_skin": [len(s.get("joints", [])) for s in document.get("skins", [])],
        "animations": [a.get("name") for a in document.get("animations", [])],
        "materials": [m.get("name") for m in document.get("materials", [])],
        "head_nodes": [n.get("name") for n in document.get("nodes", []) if "head" in n.get("name", "").lower()],
        "extensions_required": document.get("extensionsRequired", []),
        "external_dependencies": [x["uri"] for k in ("buffers", "images") for x in document.get(k, []) if "uri" in x and not x["uri"].startswith("data:")],
        "note": "Character-select model. Textures are supplied separately by the web viewer; material bindings may need reconstruction using viewer_config.json. Asset ownership remains with Riot Games; no new reuse license is granted by this download.",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
