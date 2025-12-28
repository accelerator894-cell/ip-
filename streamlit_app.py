import streamlit as st
import requests
import time
import re
import random
import json
import pandas as pd
import concurrent.futures
import socket
import threading
import ipaddress
from datetime import datetime
import urllib3
import logging
from pathlib import Path
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 日志 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[logging.FileHandler("cf_hunter.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

# ================= 路径 =================
BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "crawlers": BASE_DIR / "crawler_pool.json",
    "niches": BASE_DIR / "niche_pool.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json",
    "fail": BASE_DIR / "fail_count.json"
}

# ================= 默认配置 =================
DEFAULT_CONFIG = {
    "mode": "☀️ 正常使用排位",
    "host": "speed.cloudflare.com",
    "port": 443,
    "max_workers": 60,
    "connect_timeout": 1.0,
    "download_timeout": 4.0,
    "geo_cache_hours": 6,
    "test_bytes_by_mode": {
        "☀️ 正常使用排位": 200_000,
        "⚡ 极速低延迟": 80_000,
        "🤖 GPT 独享专线": 150_000,
        "🎬 流媒体解锁专线": 400_000,
    }
}

# ================= 常量 =================
GOLDEN_SUBNETS = [
    "104.16.0.0/12", "104.21.0.0/16",
    "172.64.0.0/13", "162.158.0.0/15",
    "188.114.96.0/20"
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1",
    "104.18.20.126", "172.67.69.1"
]

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港",
    "JP": "日本", "KR": "韩国", "TW": "台湾",
    "DE": "德国", "GB": "英国"
}

geo_cache = {}
fail_counts = defaultdict(int)

# ================= 工具函数 =================
def safe_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except:
        return default if default is not None else {}

def safe_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def fast_tcp_check(ip, port=443, timeout=0.4):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except:
        return False

def is_real_cf_edge(ip, timeout=1.0):
    try:
        r = requests.get(f"http://{ip}/cdn-cgi/trace", timeout=timeout)
        return "colo=" in r.text
    except:
        return False

def get_geo_info(ip):
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    try:
        r = requests.get(f"https://ipinfo.io/{ip}/json", timeout=2)
        d = r.json()
        data = {
            "cc": d.get("country", "??"),
            "country": d.get("country", "未知")
        }
    except:
        data = {"cc": "??", "country": "未知"}

    geo_cache[ip] = {
        "data": data,
        "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]
    }
    return data

def build_hot_subnets(db, min_score=60):
    counter = defaultdict(int)
    for ip, v in db.items():
        if v.get("score", 0) >= min_score:
            subnet = ".".join(ip.split(".")[:3])
            counter[subnet] += 1
    return sorted(counter, key=counter.get, reverse=True)[:20]

# ================= IP 池管理 =================
class IPPoolManager:

    @staticmethod
    def blacklist():
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_black(ip):
        bl = IPPoolManager.blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=80):
        pool = safe_json(FILES["crawlers"], {"raw": [], "verified": [], "elite": []})
        bl = IPPoolManager.blacklist()

        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/"
        ]

        raw, verified = set(pool["raw"]), set(pool["verified"])

        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
                for ip in ips:
                    if ip in bl or ip in raw or ip in verified:
                        continue
                    if not fast_tcp_check(ip):
                        continue
                    raw.add(ip)
                    if is_real_cf_edge(ip):
                        verified.add(ip)
            except:
                continue

        pool["raw"] = list(raw)[:max_size * 2]
        pool["verified"] = list(verified)[:max_size]
        safe_write_json(FILES["crawlers"], pool)

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = set(safe_json(FILES["niches"], []))
        bl = IPPoolManager.blacklist()
        db = safe_json(FILES["database"], {})
        hot = build_hot_subnets(db)

        new = set()
        for _ in range(max_size * 6):
            if hot and random.random() < 0.7:
                base = random.choice(hot)
                ip = f"{base}.{random.randint(1,254)}"
            else:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                ip = str(net.network_address + random.randint(1, net.num_addresses - 3))

            if ip in bl or ip in current:
                continue
            if fast_tcp_check(ip):
                new.add(ip)

        safe_write_json(FILES["niches"], list(current | new)[:max_size])

# ================= 核心进化引擎 =================
def evolution_engine():
    db = safe_json(FILES["database"], {})
    global fail_counts
    fail_counts = defaultdict(int, safe_json(FILES["fail"], {}))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())

            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            is_full_scan = int(time.time()) % 300 < 8
            targets = []

            crawler = safe_json(FILES["crawlers"], {})
            if is_full_scan:
                targets += [{"ip": ip, "src": "📂 全量"} for ip in db.keys()]
            else:
                targets += [{"ip": ip, "src": "🏆 Elite"} for ip in crawler.get("elite", [])]
                targets += [{"ip": ip, "src": "🟢 Verified"} for ip in crawler.get("verified", [])]
                targets += [{"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], [])]
                targets += [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]

            results = []

            def test_ip(t):
                ip = t["ip"]
                try:
                    with socket.socket() as s:
                        s.settimeout(cfg["connect_timeout"])
                        t0 = time.perf_counter()
                        s.connect((ip, cfg["port"]))
                        tcp_ms = (time.perf_counter() - t0) * 1000

                    bytes_test = cfg["test_bytes_by_mode"][cfg["mode"]]
                    st0 = time.perf_counter()
                    r = requests.get(
                        f"http://{ip}/__down?bytes={bytes_test}",
                        headers={"Host": cfg["host"]},
                        timeout=cfg["download_timeout"],
                        stream=True
                    )
                    size = sum(len(c) for c in r.iter_content(65536))
                    elapsed = time.perf_counter() - st0
                    speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0

                    geo = get_geo_info(ip)
                    score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1)

                    result = {
                        "ip": ip,
                        "score": score,
                        "avg": round(tcp_ms, 1),
                        "speed": round(speed, 2),
                        "src": t["src"],
                        "cc": geo["cc"],
                        "country": geo["country"],
                        "last_test": datetime.now().strftime("%H:%M:%S")
                    }

                    db[ip] = result
                    fail_counts[ip] = 0

                    if score >= 80:
                        pool = safe_json(FILES["crawlers"], {})
                        elite = set(pool.get("elite", []))
                        elite.add(ip)
                        pool["elite"] = list(elite)[:40]
                        safe_write_json(FILES["crawlers"], pool)

                    return result

                except:
                    fail_counts[ip] += 1
                    if fail_counts[ip] >= 7:
                        IPPoolManager.add_black(ip)
                    return None

            with concurrent.futures.ThreadPoolExecutor(cfg["max_workers"]) as ex:
                for r in ex.map(test_ip, targets[:400]):
                    if r:
                        results.append(r)

            if results:
                results.sort(key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "winner": results[0],
                    "table": results[:20],
                    "mode": cfg["mode"],
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "is_full": is_full_scan
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail"], dict(fail_counts))

        except Exception as e:
            logger.error(e)

        time.sleep(4)

# ================= UI =================
if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config("Cloudflare 猎手 · 进化版", "🧬", layout="wide")

with st.sidebar:
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(cfg["test_bytes_by_mode"].keys())
    mode = st.radio("优选策略", modes, index=modes.index(cfg["mode"]))
    if st.button("保存配置"):
        cfg["mode"] = mode
        safe_write_json(FILES["config"], cfg)
        st.rerun()

data = safe_json(FILES["results"], {})
st.title("🧬 Cloudflare 猎手 · 进化版")

if not data:
    st.info("引擎启动中，首次结果约 10~30 秒")
    st.stop()

w = data["winner"]
st.metric("最优 IP", w["ip"])
st.metric("评分", w["score"])
st.metric("延迟 ms", w["avg"])
st.metric("速度 MB/s", w["speed"])

df = pd.DataFrame(data["table"])
df["地区"] = df["cc"].map(lambda x: f"{x} {COUNTRY_MAP.get(x,'')}")
st.dataframe(df, use_container_width=True)