from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import requests, json, re, time, threading, os
import xml.etree.ElementTree as ET

CACHE = {}
LOCK = threading.Lock()
COOKIE = os.environ.get("ROBLOSECURITY", "")

HEADERS = {"User-Agent": "Roblox/WinInet", "Accept": "application/json"}
if COOKIE:
    HEADERS["Cookie"] = f".ROBLOSECURITY={COOKIE}"

def cache_get(k):
    with LOCK:
        i = CACHE.get(k)
        if i and time.time() - i["ts"] < 600:
            return i["val"]
    return None

def cache_set(k, v):
    with LOCK:
        CACHE[k] = {"val": v, "ts": time.time()}

def resolve_asset(aid):
    aid = str(aid)
    c = cache_get("a:" + aid)
    if c: return c
    r = {"assetId": aid, "name": "", "meshId": None, "textureId": None, "error": None}
    try:
        resp = requests.get(f"https://assetdelivery.roblox.com/v1/asset?id={aid}", headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            r["error"] = f"HTTP {resp.status_code}"
            return r
        xml = resp.text
        if "<roblox" in xml.lower():
            try:
                root = ET.fromstring(xml)
                r["name"] = root.attrib.get("name", "")
                for item in root.iter():
                    tag = item.tag.lower()
                    if tag == "content":
                        n = (item.attrib.get("name") or "").lower()
                        v = (item.text or "").strip()
                        if n == "mesh" and not r["meshId"]: r["meshId"] = v
                        elif n == "texture" and not r["textureId"]: r["textureId"] = v
                    elif tag == "specialmesh":
                        m = item.attrib.get("MeshId")
                        t = item.attrib.get("TextureId")
                        if m and not r["meshId"]: r["meshId"] = m
                        if t and not r["textureId"]: r["textureId"] = t
            except: pass
            if not r["meshId"]:
                m = re.search(r'MeshId["\']?\s*[:=]\s*["\']?(?:rbxassetid://)?(\d+)', xml)
                if m: r["meshId"] = "rbxassetid://" + m.group(1)
            if not r["textureId"]:
                m = re.search(r'TextureId["\']?\s*[:=]\s*["\']?(?:rbxassetid://)?(\d+)', xml)
                if m: r["textureId"] = "rbxassetid://" + m.group(1)
            for k in ("meshId", "textureId"):
                if r[k]:
                    n = re.search(r'(\d+)', str(r[k]))
                    if n: r[k] = "rbxassetid://" + n.group(1)
    except Exception as e:
        r["error"] = str(e)
    cache_set("a:" + aid, r)
    return r

def get_uid(uname):
    c = cache_get("u:" + uname.lower())
    if c: return c
    try:
        resp = requests.post("https://users.roblox.com/v1/usernames/users",
            headers={**HEADERS, "Content-Type": "application/json"},
            json={"usernames": [uname]}, timeout=10)
        d = resp.json()
        if d.get("data"):
            uid = d["data"][0]["id"]
            cache_set("u:" + uname.lower(), uid)
            return uid
    except: pass
    return None

def get_outfit(uid):
    c = cache_get(f"o:{uid}")
    if c: return c
    r = {"userId": uid, "accessories": [], "error": None}
    try:
        resp = requests.get(f"https://avatar.roblox.com/v1/users/{uid}/avatar", headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            r["error"] = f"HTTP {resp.status_code}"
            return r
        d = resp.json()
        slots = ["hatAccessories","hairAccessories","faceAccessories","neckAccessories",
                 "shoulderAccessories","frontAccessories","backAccessories","waistAccessories"]
        seen = set()
        for s in slots:
            for item in d.get(s, []):
                aid = item.get("id")
                if aid and aid not in seen:
                    seen.add(aid)
                    r["accessories"].append({"slot": s, "id": aid, "name": item.get("name", ""), "resolved": resolve_asset(aid)})
        cache_set(f"o:{uid}", r)
    except Exception as e:
        r["error"] = str(e)
    return r

class H(BaseHTTPRequestHandler):
    def _j(self, o, s=200):
        try:
            b = json.dumps(o).encode()
            self.send_response(s)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b)
        except: pass
    def log_message(self, f, *a): pass
    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)
        path = p.path.rstrip("/")
        if path in ("", "/"):
            self._j({"status": "ok", "server": "Rotex3XP Resolver",
                "endpoints": ["/resolve?id=", "/outfit?userId=", "/outfit?user=", "/userid?user="]})
            return
        if path == "/resolve":
            aid = q.get("id", [None])[0]
            if not aid: self._j({"error": "missing id"}, 400); return
            self._j(resolve_asset(aid)); return
        if path == "/userid":
            u = q.get("user", [None])[0]
            if not u: self._j({"error": "missing user"}, 400); return
            self._j({"username": u, "userId": get_uid(u)}); return
        if path == "/outfit":
            uid = q.get("userId", [None])[0]
            uname = q.get("user", [None])[0]
            if not uid and uname: uid = get_uid(uname)
            if not uid: self._j({"error": "missing userId/user"}, 400); return
            self._j(get_outfit(uid)); return
        self._j({"error": "unknown"}, 404)

PORT = int(os.environ.get("PORT", 8080))
print(f"Server jalan di port {PORT}")
ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()