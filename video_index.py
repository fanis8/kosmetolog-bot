import json
import os
import re

VIDEO_DIR = os.environ.get("VIDEO_DIR", os.path.expandvars(r"%USERPROFILE%\Documents\OpenCode_Проект_1\Косметолог\video_перевод"))
INDEX_FILE = os.path.join(os.path.dirname(__file__), "data", "videos.json")

VIDEO_PATTERN = re.compile(r"^(\d+)-(\d+)-(.+)\.mp4$")

def build_index():
    videos = []
    pages = {}
    if not os.path.isdir(VIDEO_DIR):
        return {"videos": videos, "pages": pages}
    for entry in os.scandir(VIDEO_DIR):
        if not entry.is_dir():
            continue
        page_raw = entry.name.removeprefix("видео_стр")
        if not page_raw.isdigit():
            continue
        page_num = int(page_raw)
        page_key = str(page_num)
        pages.setdefault(page_key, [])
        for f in os.scandir(entry.path):
            if not f.name.endswith(".mp4"):
                continue
            m = VIDEO_PATTERN.match(f.name)
            if not m:
                continue
            vid_num = int(m.group(1))
            seq_num = int(m.group(2))
            desc = m.group(3)
            info = {
                "page": page_key,
                "vid_num": vid_num,
                "seq": seq_num,
                "desc": desc,
                "filename": f.name,
                "path": f.path,
                "size_mb": round(f.stat().st_size / 1048576, 1),
                "yandex_url": None,
            }
            videos.append(info)
            pages[page_key].append({
                "num": seq_num,
                "desc": desc,
                "filename": f.name,
            })
    videos.sort(key=lambda x: (x["vid_num"], x["seq"]))
    for k in pages:
        pages[k].sort(key=lambda x: x["num"])
    index = {"videos": videos, "pages": pages}
    os.makedirs(os.path.dirname(INDEX_FILE), exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as fp:
        json.dump(index, fp, ensure_ascii=False, indent=2)
    return index

def load_index():
    if not os.path.exists(INDEX_FILE):
        return build_index()
    with open(INDEX_FILE, "r", encoding="utf-8") as fp:
        return json.load(fp)

def find_by_page(index, page):
    return index["pages"].get(str(page), [])

def find_one(index, page, seq):
    page = str(page)
    for v in index["videos"]:
        if v["page"] == page and v["seq"] == seq:
            return v
    return None

def search_by_text(index, query):
    q = query.lower()
    results = []
    for v in index["videos"]:
        if q in v["desc"].lower():
            results.append(v)
    return results

if __name__ == "__main__":
    idx = build_index()
    print(f"Проиндексировано {len(idx['videos'])} видео в {len(idx['pages'])} страницах")