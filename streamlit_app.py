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

# ================= 基础配置 =================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')]
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
FILES = {
    "results": BASE_DIR / "scan_results.json",
    "database": BASE_DIR / "ip_database.json",
    "crawlers": BASE_DIR / "crawler_pool.json",
    "niches": BASE_DIR / "niche_pool.json",
    "config": BASE_DIR / "app_config.json",
    "blacklist": BASE_DIR / "blacklist.json",
    "fail_count": BASE_DIR / "fail_count.json"
}

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
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本",
    "KR": "韩国", "TW": "台湾", "DE": "德国", "GB": "英国"
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
    def get_blacklist():
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_black(ip):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=80):
        pool = safe_json(FILES["crawlers"], {"raw": [], "verified": [], "elite": []})
        blacklist = IPPoolManager.get_blacklist()

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
                    if ip in blacklist or ip in raw or ip in verified:
                        continue
                    if not fast_tcp_check(ip):
                        continue
                    raw.add(ip)
                    if is_real_cf_edge(ip):
                        verified.add(ip)
                    if len(verified) >= max_size:
                        break
            except:
                continue

        pool["raw"] = list(raw)[:max_size * 2]
        pool["verified"] = list(verified)[:max_size]
        safe_write_json(FILES["crawlers"], pool)

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = set(safe_json(FILES["niches"], []))
        blacklist = IPPoolManager.get_blacklist()
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

            if ip in blacklist or ip in current:
                continue
            if fast_tcp_check(ip):
                new.add(ip)

        safe_write_json(FILES["niches"], list(current | new)[:max_size])

# ================= 核心进化引擎 =================

def evolution_engine():
    db = safe_json(FILES["database"], {})
    global fail_counts
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"], {}))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())

            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            crawler = safe_json(FILES["crawlers"], {})
            targets = []

            targets += [{"ip": ip, "src": "🏆 Elite"} for ip in crawler.get("elite", [])]
            targets += [{"ip": ip, "src": "🟢 Verified"} for ip in crawler.get("verified", [])]
            targets += [{"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], [])]
            targets += [{"ip": ip, "src": "⚡ 种子"} for ip in QUICK_SEEDS]

            results = []

            def test_ip(t):
                ip = t["ip"]
                try:
                    if not fast_tcp_check(ip, timeout=cfg["connect_timeout"]):
                        raise Exception

                    start = time.perf_counter()
                    r = requests.get(
                        f"http://{ip}/__down?bytes={cfg['test_bytes_by_mode'][cfg['mode']]}",
                        headers={"Host": cfg["host"]},
                        timeout=cfg["download_timeout"],
                        stream=True
                    )
                    size = sum(len(c) for c in r.iter_content(65536))
                    elapsed = time.perf_counter() - start
                    speed = size / elapsed / 1024 / 1024

                    score = round(100 + speed * 6, 1)
                    db[ip] = {
                        "ip": ip,
                        "score": score,
                        "speed": round(speed, 2),
                        "src": t["src"],
                        "last_test": datetime.now().strftime("%H:%M:%S")
                    }

                    if score >= 80:
                        pool = safe_json(FILES["crawlers"], {})
                        elite = set(pool.get("elite", []))
                        elite.add(ip)
                        pool["elite"] = list(elite)[:40]
                        safe_write_json(FILES["crawlers"], pool)

                    fail_counts[ip] = 0
                    return db[ip]
                except:
                    fail_counts[ip] += 1
                    if fail_counts[ip] >= 7:
                        IPPoolManager.add_black(ip)
                    return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as ex:
                for r in ex.map(test_ip, targets[:300]):
                    if r:
                        results.append(r)

            if results:
                results.sort(key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "winner": results[0],
                    "table": results[:20],
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "mode": cfg["mode"]
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(e)

        time.sleep(4)

# ================= Streamlit UI =================

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config("Cloudflare 猎手 · 进化版", "🧬", layout="wide")
data = safe_json(FILES["results"], {})

st.title("🧬 Cloudflare 猎手 · 进化版")

if not data:
    st.info("引擎启动中，首次结果约 10~30 秒")
    st.stop()

winner = data["winner"]
st.metric("最优 IP", winner["ip"])
st.metric("评分", winner["score"])
st.metric("速度 MB/s", winner["speed"])

df = pd.DataFrame(data["table"])
st.dataframe(df, use_container_width=True)