import time, json, random, socket, threading
from pathlib import Path
from collections import defaultdict, Counter
import requests

BASE = Path(".")
DB_FILE = BASE / "ip_db.json"
STATE_FILE = BASE / "state.json"
FAIL_FILE = BASE / "fail_db.json"

UUID = "填写你的UUID"
REALITY_PUB = "填写你的Reality公钥"
REALITY_SID = "填写你的short_id"
SNI = "www.cloudflare.com"

SCENES = ["normal", "gpt", "stream"]

FINGERPRINT = {
    "normal": "chrome",
    "gpt": "firefox",
    "stream": "safari"
}

SEEDS = [
    "104.19.19.19", "104.18.20.126",
    "172.64.198.1", "172.67.1.1"
]

def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())

def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

# ---------- IP 测试 ----------
def test_ip(ip):
    try:
        s = socket.socket()
        s.settimeout(1)
        t0 = time.time()
        s.connect((ip, 443))
        latency = (time.time() - t0) * 1000
        s.close()

        r = requests.get(
            f"http://{ip}/cdn-cgi/trace",
            headers={"Host": SNI},
            timeout=2
        )
        colo = "UNK"
        if "colo=" in r.text:
            colo = r.text.split("colo=")[1].split("\n")[0]

        return latency, colo
    except:
        return None, None

# ---------- 稳定度模型 ----------
def colo_stability(colos):
    if not colos:
        return 0
    c = Counter(colos)
    return c.most_common(1)[0][1] / len(colos)

def health_score(h):
    return round(
        colo_stability(h["colo"]) * 0.4 +
        (1 - min(sum(h["latency"]) / len(h["latency"]) / 200, 1)) * 0.3 +
        min(h["success"] / max(h["success"] + h["fail"], 1), 1) * 0.3,
        3
    )

# ---------- 是否切 IP ----------
def should_switch(cur, cand):
    if cur is None:
        return True
    if cur["health"] >= 0.85:
        return False
    return cand["health"] - cur["health"] >= 0.15

# ---------- NekoBox 输出 ----------
def export_nekobox(scene, ip):
    node = {
        "type": "vless",
        "tag": f"CF-{scene.upper()}",
        "server": ip,
        "server_port": 443,
        "uuid": UUID,
        "tls": {
            "enabled": True,
            "server_name": SNI,
            "utls": {
                "enabled": True,
                "fingerprint": FINGERPRINT[scene]
            },
            "reality": {
                "enabled": True,
                "public_key": REALITY_PUB,
                "short_id": REALITY_SID
            }
        },
        "transport": {"type": "tcp"}
    }
    save(BASE / f"nekobox_{scene}.json", node)

# ---------- 主循环 ----------
def scheduler():
    db = load(DB_FILE, {})
    state = load(STATE_FILE, {})
    fail = load(FAIL_FILE, defaultdict(int))

    while True:
        for ip in SEEDS:
            lat, colo = test_ip(ip)
            if not lat:
                fail[ip] = fail.get(ip, 0) + 1
                continue

            h = db.get(ip, {
                "latency": [],
                "colo": [],
                "success": 0,
                "fail": 0
            })

            h["latency"].append(lat)
            h["latency"] = h["latency"][-10:]
            h["colo"].append(colo)
            h["colo"] = h["colo"][-10:]
            h["success"] += 1

            h["health"] = health_score(h)
            db[ip] = h

            for scene in SCENES:
                cur_ip = state.get(scene)
                cur = db.get(cur_ip) if cur_ip else None
                if should_switch(cur, h):
                    state[scene] = ip
                    export_nekobox(scene, ip)

        save(DB_FILE, db)
        save(STATE_FILE, state)
        save(FAIL_FILE, fail)
        time.sleep(10)

if __name__ == "__main__":
    scheduler()