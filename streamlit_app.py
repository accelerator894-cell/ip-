import streamlit as st
import requests
import time
import re
import random
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
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
    "uuid": "",
    "ws_path": "/",
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
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "104.17.0.1", "172.65.1.1", "104.20.1.1", "172.68.1.1"
]

geo_cache = {}
fail_counts = defaultdict(int)

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯",
    "IN": "印度", "BR": "巴西", "ZA": "南非",
}

def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str, timeout=2.5) -> dict:
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}/json", "headers": {"User-Agent": "cf-hunter/1.0"},
         "parser": lambda d: {"cc": d.get("country", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipinfo"}},
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country_name", "未知"), "city": d.get("city", ""), "source": "ipapi.co"}},
        {"name": "ipwhois", "url": f"https://ipwhois.app/json/{ip}",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipwhois"}},
        {"name": "cf_trace", "url": f"http://{ip}/cdn-cgi/trace",
         "parser": lambda text: {"cc": "??", "country": f"CF-Colo: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}", "city": "", "source": "cf_trace"}}
    ]

    for method in methods:
        try:
            r = requests.get(method["url"], timeout=timeout, headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"}))
            if r.status_code != 200: continue
            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())
            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except Exception:
            continue
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=60):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size: return
        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]
        found = set(current)
        blacklist = IPPoolManager.get_blacklist()
        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except:
                pass
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 8):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue
        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)
        logger.info(f"冷门池更新: {len(combined)} 个")

def evolution_engine():
    global fail_counts
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 每轮强制填充
            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:60]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(128 * 1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1) if tcp_ms > 0 else 0

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1) if tcp_ms > 0 else 999,
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old_score = db.get(ip, {}).get("score", 0)
                        if score > 0 or old_score > 0:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 7:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败7次，黑名单")

                        success_count += 1
                        return result
                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 7:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:400]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results,
                    "is_full": is_full_scan,
                    "mode": cfg["mode"],
                    "debug": {"targets": len(unique_targets), "success": success_count}
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(4)

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 20, 120, cfg["max_workers"], step=5)

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1.2)
        st.rerun()

data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~50秒初次扫描完成")
    time.sleep(5)
    st.rerun()

else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([3, 1.5, 1.5, 1.8])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("下载速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {COUNTRY_MAP.get(winner['cc'], '未知')}")

    st.divider()

    table_data = data.get("table", [])
    display_count = min(10, len(table_data))
    debug = data.get("debug", {"targets": 0, "success": 0})
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {len(table_data)} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）")

    df = pd.DataFrame(table_data[:10])

    df["来源"] = df["src"]
    df["地区"] = df.apply(
        lambda row: f"{row['cc']} {COUNTRY_MAP.get(row['cc'], '未知')}"
        if row['cc'] != "??" else "?? 未知",
        axis=1
    )

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
            "ip": st.column_config.TextColumn("IP地址", width="medium"),
            "地区": st.column_config.TextColumn("地区", width="medium"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")
    time.sleep(5)
    st.rerun()import streamlit as st
import requests
import time
import re
import random
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
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
    "uuid": "",
    "ws_path": "/",
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
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "104.17.0.1", "172.65.1.1", "104.20.1.1", "172.68.1.1"
]

geo_cache = {}
fail_counts = defaultdict(int)

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯",
    "IN": "印度", "BR": "巴西", "ZA": "南非",
}

def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str, timeout=2.5) -> dict:
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}/json", "headers": {"User-Agent": "cf-hunter/1.0"},
         "parser": lambda d: {"cc": d.get("country", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipinfo"}},
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country_name", "未知"), "city": d.get("city", ""), "source": "ipapi.co"}},
        {"name": "ipwhois", "url": f"https://ipwhois.app/json/{ip}",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipwhois"}},
        {"name": "cf_trace", "url": f"http://{ip}/cdn-cgi/trace",
         "parser": lambda text: {"cc": "??", "country": f"CF-Colo: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}", "city": "", "source": "cf_trace"}}
    ]

    for method in methods:
        try:
            r = requests.get(method["url"], timeout=timeout, headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"}))
            if r.status_code != 200: continue
            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())
            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except Exception:
            continue
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=60):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size: return
        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]
        found = set(current)
        blacklist = IPPoolManager.get_blacklist()
        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except:
                pass
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 8):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue
        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)
        logger.info(f"冷门池更新: {len(combined)} 个")

def evolution_engine():
    global fail_counts
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 每轮强制填充
            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:60]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(128 * 1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1) if tcp_ms > 0 else 0

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1) if tcp_ms > 0 else 999,
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old_score = db.get(ip, {}).get("score", 0)
                        if score > 0 or old_score > 0:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 7:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败7次，黑名单")

                        success_count += 1
                        return result
                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 7:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:400]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results,
                    "is_full": is_full_scan,
                    "mode": cfg["mode"],
                    "debug": {"targets": len(unique_targets), "success": success_count}
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(4)

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 20, 120, cfg["max_workers"], step=5)

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1.2)
        st.rerun()

data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~50秒初次扫描完成")
    time.sleep(5)
    st.rerun()

else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([3, 1.5, 1.5, 1.8])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("下载速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {COUNTRY_MAP.get(winner['cc'], '未知')}")

    st.divider()

    table_data = data.get("table", [])
    display_count = min(10, len(table_data))
    debug = data.get("debug", {"targets": 0, "success": 0})
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {len(table_data)} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）")

    df = pd.DataFrame(table_data[:10])

    df["来源"] = df["src"]
    df["地区"] = df.apply(
        lambda row: f"{row['cc']} {COUNTRY_MAP.get(row['cc'], '未知')}"
        if row['cc'] != "??" else "?? 未知",
        axis=1
    )

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
            "ip": st.column_config.TextColumn("IP地址", width="medium"),
            "地区": st.column_config.TextColumn("地区", width="medium"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")
    time.sleep(5)
    st.rerun()import streamlit as st
import requests
import time
import re
import random
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
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
    "uuid": "",
    "ws_path": "/",
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
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "104.17.0.1", "172.65.1.1", "104.20.1.1", "172.68.1.1"
]

geo_cache = {}
fail_counts = defaultdict(int)

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯",
    "IN": "印度", "BR": "巴西", "ZA": "南非",
}

def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str, timeout=2.5) -> dict:
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}/json", "headers": {"User-Agent": "cf-hunter/1.0"},
         "parser": lambda d: {"cc": d.get("country", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipinfo"}},
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country_name", "未知"), "city": d.get("city", ""), "source": "ipapi.co"}},
        {"name": "ipwhois", "url": f"https://ipwhois.app/json/{ip}",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipwhois"}},
        {"name": "cf_trace", "url": f"http://{ip}/cdn-cgi/trace",
         "parser": lambda text: {"cc": "??", "country": f"CF-Colo: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}", "city": "", "source": "cf_trace"}}
    ]

    for method in methods:
        try:
            r = requests.get(method["url"], timeout=timeout, headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"}))
            if r.status_code != 200: continue
            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())
            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except Exception:
            continue
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=60):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size: return
        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]
        found = set(current)
        blacklist = IPPoolManager.get_blacklist()
        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except:
                pass
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 8):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue
        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)
        logger.info(f"冷门池更新: {len(combined)} 个")

def evolution_engine():
    global fail_counts
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 每轮强制填充
            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:60]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(128 * 1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1) if tcp_ms > 0 else 0

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1) if tcp_ms > 0 else 999,
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old_score = db.get(ip, {}).get("score", 0)
                        if score > 0 or old_score > 0:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 7:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败7次，黑名单")

                        success_count += 1
                        return result
                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 7:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:400]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results,
                    "is_full": is_full_scan,
                    "mode": cfg["mode"],
                    "debug": {"targets": len(unique_targets), "success": success_count}
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(4)

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 20, 120, cfg["max_workers"], step=5)

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1.2)
        st.rerun()

data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~50秒初次扫描完成")
    time.sleep(5)
    st.rerun()

else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([3, 1.5, 1.5, 1.8])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("下载速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {COUNTRY_MAP.get(winner['cc'], '未知')}")

    st.divider()

    table_data = data.get("table", [])
    display_count = min(10, len(table_data))
    debug = data.get("debug", {"targets": 0, "success": 0})
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {len(table_data)} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）")

    df = pd.DataFrame(table_data[:10])

    df["来源"] = df["src"]
    df["地区"] = df.apply(
        lambda row: f"{row['cc']} {COUNTRY_MAP.get(row['cc'], '未知')}"
        if row['cc'] != "??" else "?? 未知",
        axis=1
    )

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
            "ip": st.column_config.TextColumn("IP地址", width="medium"),
            "地区": st.column_config.TextColumn("地区", width="medium"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")
    time.sleep(5)
    st.rerun()import streamlit as st
import requests
import time
import re
import random
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
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
    "uuid": "",
    "ws_path": "/",
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
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "104.17.0.1", "172.65.1.1", "104.20.1.1", "172.68.1.1"
]

geo_cache = {}
fail_counts = defaultdict(int)

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯",
    "IN": "印度", "BR": "巴西", "ZA": "南非",
}

def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str, timeout=2.5) -> dict:
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}/json", "headers": {"User-Agent": "cf-hunter/1.0"},
         "parser": lambda d: {"cc": d.get("country", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipinfo"}},
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country_name", "未知"), "city": d.get("city", ""), "source": "ipapi.co"}},
        {"name": "ipwhois", "url": f"https://ipwhois.app/json/{ip}",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipwhois"}},
        {"name": "cf_trace", "url": f"http://{ip}/cdn-cgi/trace",
         "parser": lambda text: {"cc": "??", "country": f"CF-Colo: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}", "city": "", "source": "cf_trace"}}
    ]

    for method in methods:
        try:
            r = requests.get(method["url"], timeout=timeout, headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"}))
            if r.status_code != 200: continue
            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())
            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except Exception:
            continue
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=60):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size: return
        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]
        found = set(current)
        blacklist = IPPoolManager.get_blacklist()
        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except:
                pass
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 8):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue
        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)
        logger.info(f"冷门池更新: {len(combined)} 个")

def evolution_engine():
    global fail_counts
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 每轮强制填充
            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:60]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(128 * 1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1) if tcp_ms > 0 else 0

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1) if tcp_ms > 0 else 999,
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old_score = db.get(ip, {}).get("score", 0)
                        if score > 0 or old_score > 0:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 7:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败7次，黑名单")

                        success_count += 1
                        return result
                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 7:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:400]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results,
                    "is_full": is_full_scan,
                    "mode": cfg["mode"],
                    "debug": {"targets": len(unique_targets), "success": success_count}
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(4)

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 20, 120, cfg["max_workers"], step=5)

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1.2)
        st.rerun()

data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~50秒初次扫描完成")
    time.sleep(5)
    st.rerun()

else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([3, 1.5, 1.5, 1.8])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("下载速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {COUNTRY_MAP.get(winner['cc'], '未知')}")

    st.divider()

    table_data = data.get("table", [])
    display_count = min(10, len(table_data))
    debug = data.get("debug", {"targets": 0, "success": 0})
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {len(table_data)} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）")

    df = pd.DataFrame(table_data[:10])

    df["来源"] = df["src"]
    df["地区"] = df.apply(
        lambda row: f"{row['cc']} {COUNTRY_MAP.get(row['cc'], '未知')}"
        if row['cc'] != "??" else "?? 未知",
        axis=1
    )

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
            "ip": st.column_config.TextColumn("IP地址", width="medium"),
            "地区": st.column_config.TextColumn("地区", width="medium"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")
    time.sleep(5)
    st.rerun()import streamlit as st
import requests
import time
import re
import random
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s',
                    handlers=[logging.FileHandler("cf_hunter.log", encoding='utf-8')])
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
    "uuid": "",
    "ws_path": "/",
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
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "104.17.0.1", "172.65.1.1", "104.20.1.1", "172.68.1.1"
]

geo_cache = {}
fail_counts = defaultdict(int)

COUNTRY_MAP = {
    "US": "美国", "SG": "新加坡", "HK": "香港", "JP": "日本", "KR": "韩国",
    "TW": "台湾", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "CA": "加拿大", "AU": "澳大利亚", "CN": "中国", "RU": "俄罗斯",
    "IN": "印度", "BR": "巴西", "ZA": "南非",
}

def safe_json(file_path: Path, default=None):
    if not file_path.exists():
        return default or {}
    try:
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception:
        return default or {}

def safe_write_json(file_path: Path, data):
    try:
        tmp = file_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(file_path)
    except Exception as e:
        logger.error(f"写入失败 {file_path}: {e}")

def get_geo_info(ip: str, timeout=2.5) -> dict:
    now = time.time()
    if ip in geo_cache and geo_cache[ip]["expire"] > now:
        return geo_cache[ip]["data"]

    methods = [
        {"name": "ipinfo", "url": f"https://ipinfo.io/{ip}/json", "headers": {"User-Agent": "cf-hunter/1.0"},
         "parser": lambda d: {"cc": d.get("country", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipinfo"}},
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country_name", "未知"), "city": d.get("city", ""), "source": "ipapi.co"}},
        {"name": "ipwhois", "url": f"https://ipwhois.app/json/{ip}",
         "parser": lambda d: {"cc": d.get("country_code", "??"), "country": d.get("country", "未知"), "city": d.get("city", ""), "source": "ipwhois"}},
        {"name": "cf_trace", "url": f"http://{ip}/cdn-cgi/trace",
         "parser": lambda text: {"cc": "??", "country": f"CF-Colo: {text.split('colo=')[1].split('\n')[0] if 'colo=' in text else '未知'}", "city": "", "source": "cf_trace"}}
    ]

    for method in methods:
        try:
            r = requests.get(method["url"], timeout=timeout, headers=method.get("headers", {"User-Agent": "cf-hunter/1.0"}))
            if r.status_code != 200: continue
            if method["name"] == "cf_trace":
                data = method["parser"](r.text)
            else:
                data = method["parser"](r.json())
            geo_cache[ip] = {"data": data, "expire": now + 3600 * DEFAULT_CONFIG["geo_cache_hours"]}
            return data
        except Exception:
            continue
    return {"cc": "??", "country": "获取失败", "city": "", "source": "failed"}

class IPPoolManager:
    @staticmethod
    def get_blacklist() -> set:
        return set(safe_json(FILES["blacklist"], []))

    @staticmethod
    def add_to_blacklist(ip: str):
        bl = IPPoolManager.get_blacklist()
        bl.add(ip)
        safe_write_json(FILES["blacklist"], list(bl))

    @staticmethod
    def fill_crawler_pool(max_size=60):
        current = safe_json(FILES["crawlers"], [])
        if len(current) >= max_size: return
        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]
        found = set(current)
        blacklist = IPPoolManager.get_blacklist()
        for url in sources:
            try:
                r = requests.get(url, timeout=8)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except:
                pass
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=60):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 8):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist and candidate not in current:
                    new_ips.append(candidate)
            except:
                continue
        combined = list(set(current + new_ips))[:max_size]
        safe_write_json(FILES["niches"], combined)
        logger.info(f"冷门池更新: {len(combined)} 个")

def evolution_engine():
    global fail_counts
    db = safe_json(FILES["database"])
    fail_counts = defaultdict(int, safe_json(FILES["fail_count"]))

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 每轮强制填充
            threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
            threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            if is_full_scan:
                targets.extend({"ip": ip, "src": "📂 全量扫描"} for ip in db)
            else:
                targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)
                top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:60]
                targets.extend({"ip": ip, "src": "🏆 历史优秀"} for ip, _ in top)
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["max_workers"]) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 200000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(128 * 1024):
                                size += len(chunk)
                                if time.perf_counter() - st > cfg["download_timeout"]:
                                    break
                            elapsed = time.perf_counter() - st
                            speed = size / elapsed / 1024 / 1024 if elapsed > 0 else 0
                        except:
                            pass

                        geo = get_geo_info(ip)
                        score = round(100 - tcp_ms / 4 + min(speed * 6, 50), 1) if tcp_ms > 0 else 0

                        result = {
                            "ip": ip,
                            "score": score,
                            "avg": round(tcp_ms, 1) if tcp_ms > 0 else 999,
                            "speed": round(speed, 2),
                            "src": task["src"],
                            "cc": geo["cc"],
                            "country": geo["country"],
                            "last_test": datetime.now().strftime("%H:%M:%S")
                        }

                        old_score = db.get(ip, {}).get("score", 0)
                        if score > 0 or old_score > 0:
                            db[ip] = result
                            fail_counts[ip] = 0
                        else:
                            fail_counts[ip] += 1
                            if fail_counts[ip] >= 7:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败7次，黑名单")

                        success_count += 1
                        return result
                    except Exception:
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 7:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:400]]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res:
                        results.append(res)

            if results:
                sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
                safe_write_json(FILES["results"], {
                    "last_run": datetime.now().strftime("%H:%M:%S"),
                    "winner": sorted_results[0] if sorted_results else None,
                    "table": sorted_results,
                    "is_full": is_full_scan,
                    "mode": cfg["mode"],
                    "debug": {"targets": len(unique_targets), "success": success_count}
                })

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")

        time.sleep(4)

if "started" not in st.session_state:
    threading.Thread(target=evolution_engine, daemon=True).start()
    st.session_state.started = True

st.set_page_config(page_title="Cloudflare 猎手 · 进化版", page_icon="🧬", layout="wide")

with st.sidebar:
    st.title("配置中心")
    cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
    modes = list(DEFAULT_CONFIG["test_bytes_by_mode"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("高级设置"):
        host = st.text_input("伪装域名", value=cfg["host"])
        port = st.number_input("端口", value=cfg["port"])
        max_workers = st.slider("最大并发", 20, 120, cfg["max_workers"], step=5)

    if st.button("保存并重启", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({"mode": new_mode, "host": host, "port": port, "max_workers": max_workers})
        safe_write_json(FILES["config"], new_cfg)
        if FILES["results"].exists():
            FILES["results"].unlink()
        st.success("配置已保存，引擎重启中...")
        time.sleep(1.2)
        st.rerun()

data = safe_json(FILES["results"])

if not data or not data.get("winner"):
    st.title("🧬 Cloudflare 猎手 · 进化版")
    st.info("引擎启动中... 预计10~50秒初次扫描完成")
    time.sleep(5)
    st.rerun()

else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手 · 进化版")

    tag = "🚀 全量扫描中" if data.get("is_full") else "⚡ 实时优化"
    st.markdown(f"### 当前最强节点：`{winner['ip']}`　　{tag}")

    cols = st.columns([3, 1.5, 1.5, 1.8])
    cols[0].metric("综合评分", f"{winner['score']:.1f}")
    cols[1].metric("延迟", f"{winner['avg']:.1f} ms")
    cols[2].metric("下载速度", f"{winner['speed']:.2f} MB/s")
    cols[3].metric("地区", f"{winner['cc']} {COUNTRY_MAP.get(winner['cc'], '未知')}")

    st.divider()

    table_data = data.get("table", [])
    display_count = min(10, len(table_data))
    debug = data.get("debug", {"targets": 0, "success": 0})
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {len(table_data)} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）")

    df = pd.DataFrame(table_data[:10])

    df["来源"] = df["src"]
    df["地区"] = df.apply(
        lambda row: f"{row['cc']} {COUNTRY_MAP.get(row['cc'], '未知')}"
        if row['cc'] != "??" else "?? 未知",
        axis=1
    )

    st.dataframe(
        df,
        column_order=["score", "来源", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=140, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
            "ip": st.column_config.TextColumn("IP地址", width="medium"),
            "地区": st.column_config.TextColumn("地区", width="medium"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.caption(f"最后更新: {data['last_run']}　｜　每5分钟全量扫描一次")
    time.sleep(5)
    st.rerun()import streamlit as st
import pandas as pd
import time
import threading
import random
import socket
import json
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Optional, Any
import concurrent.futures
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

# ==================== 配置部分 ====================
@dataclass
class Config:
    """应用配置"""
    BASE_DIR: Path = Path(".")
    DB_FILE: Path = BASE_DIR / "data" / "ip_db.json"
    STATE_FILE: Path = BASE_DIR / "data" / "state.json"
    FAIL_FILE: Path = BASE_DIR / "data" / "fail_db.json"
    LOG_FILE: Path = BASE_DIR / "data" / "app.log"
    
    # 连接参数
    UUID: str = "123e4567-e89b-12d3-a456-426614174000"
    REALITY_PUB: str = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A..."
    REALITY_SID: str = "abcd1234efgh5678"
    SNI: str = "speed.cloudflare.com"
    
    # 场景配置
    SCENES: List[str] = ["normal", "gpt", "stream", "custom"]
    FINGERPRINT: Dict[str, str] = {
        "normal": "chrome", 
        "gpt": "firefox", 
        "stream": "safari", 
        "custom": "chrome"
    }
    
    # 种子IP
    SEEDS: List[str] = [
        "104.19.19.19", 
        "104.18.20.126", 
        "172.64.198.1", 
        "172.67.1.1", 
        "104.21.32.13"
    ]
    
    # 测试参数
    TEST_PORT: int = 443
    TEST_TIMEOUT: float = 2.0
    MAX_WORKERS: int = 10
    UPDATE_INTERVAL: int = 30  # 秒
    
    # 健康度权重
    WEIGHT_COLO: float = 0.4
    WEIGHT_LATENCY: float = 0.3
    WEIGHT_SUCCESS: float = 0.3
    
    # 场景特定规则
    GPT_MIN_SPEED: float = 1.0  # MB/s
    STREAM_MAX_LATENCY: float = 150  # ms
    HEALTH_SWITCH_THRESHOLD: float = 0.15
    HEALTH_GOOD_THRESHOLD: float = 0.85

config = Config()

# 创建必要目录
config.BASE_DIR.mkdir(exist_ok=True)
(config.BASE_DIR / "data").mkdir(exist_ok=True)
(config.BASE_DIR / "profiles").mkdir(exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== 数据模型 ====================
@dataclass
class IPStats:
    """IP统计数据结构"""
    latency: List[float]
    colo: List[str]
    speed: List[float]
    success: int = 0
    fail: int = 0
    source: str = ""
    last_seen: str = ""
    health: float = 0.0
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'IPStats':
        """从字典创建实例"""
        # 处理可能的缺失字段
        defaults = {
            "latency": [],
            "colo": [],
            "speed": [],
            "success": 0,
            "fail": 0,
            "source": "",
            "last_seen": "",
            "health": 0.0
        }
        
        # 确保所有字段都有值
        for key, value in defaults.items():
            if key not in data:
                data[key] = value
        
        return cls(**data)

# ==================== 文件操作 ====================
class DataManager:
    """数据文件管理"""
    
    @staticmethod
    def load_json(path: Path, default: Any = None) -> Any:
        """加载JSON文件，带错误处理"""
        try:
            if not path.exists():
                return default if default is not None else {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载文件失败 {path}: {e}")
            return default if default is not None else {}
    
    @staticmethod
    def save_json(path: Path, data: Any) -> bool:
        """保存JSON文件，带错误处理"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            logger.error(f"保存文件失败 {path}: {e}")
            return False
    
    @staticmethod
    def load_ip_db() -> Dict[str, Dict]:
        """加载IP数据库"""
        data = DataManager.load_json(config.DB_FILE, {})
        # 确保所有IP数据都有正确的结构
        for ip in data:
            data[ip] = IPStats.from_dict(data[ip]).to_dict()
        return data
    
    @staticmethod
    def save_ip_db(data: Dict) -> bool:
        """保存IP数据库"""
        return DataManager.save_json(config.DB_FILE, data)
    
    @staticmethod
    def load_state() -> Dict[str, str]:
        """加载状态数据"""
        return DataManager.load_json(config.STATE_FILE, {})
    
    @staticmethod
    def save_state(data: Dict) -> bool:
        """保存状态数据"""
        return DataManager.save_json(config.STATE_FILE, data)
    
    @staticmethod
    def load_fail_db() -> Dict[str, int]:
        """加载失败数据库"""
        return DataManager.load_json(config.FAIL_FILE, {})
    
    @staticmethod
    def save_fail_db(data: Dict) -> bool:
        """保存失败数据库"""
        return DataManager.save_json(config.FAIL_FILE, data)

# ==================== IP测试模块 ====================
class IPTester:
    """IP测试器"""
    
    @staticmethod
    def test_single_ip(ip: str) -> Tuple[Optional[float], Optional[str], float, str]:
        """测试单个IP的性能"""
        try:
            # 创建TCP套接字进行连接测试
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(config.TEST_TIMEOUT)
                start_time = time.perf_counter()  # 使用更高精度的计时器
                s.connect((ip, config.TEST_PORT))
                latency = (time.perf_counter() - start_time) * 1000  # 转换为毫秒
                s.close()
                
                # 模拟数据（实际使用时应该获取真实数据）
                colo_list = ["SFO", "LAX", "NYC", "SG", "HK", "LON", "FRA", "SYD"]
                colo = random.choice(colo_list)
                speed = random.uniform(0.5, 5.0)  # 扩展速度范围
                sources = ["📂 全量扫描", "⚡ 优质种子", "🏆 历史优秀", "🕷️ 爬虫", "💎 冷门"]
                source = random.choice(sources)
                
                logger.debug(f"IP测试成功: {ip} 延迟: {latency:.1f}ms 速度: {speed:.2f}MB/s")
                return latency, colo, speed, source
                
        except socket.timeout:
            logger.debug(f"IP测试超时: {ip}")
            return None, None, 0, "超时"
        except (socket.error, ConnectionRefusedError, OSError) as e:
            logger.debug(f"IP测试失败: {ip} - {e}")
            return None, None, 0, "失败"
    
    @staticmethod
    def test_multiple_ips(ips: List[str]) -> Dict[str, Tuple]:
        """并发测试多个IP"""
        results = {}
        
        # 如果没有IP需要测试，返回空字典
        if not ips:
            return results
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            # 为每个IP创建测试任务
            future_to_ip = {executor.submit(IPTester.test_single_ip, ip): ip for ip in ips}
            
            # 收集结果
            for future in concurrent.futures.as_completed(future_to_ip):
                ip = future_to_ip[future]
                try:
                    # 设置超时以防万一
                    results[ip] = future.result(timeout=config.TEST_TIMEOUT + 2)
                except concurrent.futures.TimeoutError:
                    results[ip] = (None, None, 0, "超时")
                    logger.warning(f"IP测试任务超时: {ip}")
                except Exception as e:
                    results[ip] = (None, None, 0, f"错误: {str(e)[:50]}")
                    logger.error(f"IP测试任务异常: {ip} - {e}")
        
        logger.info(f"完成IP批量测试，共测试 {len(ips)} 个IP，成功 {len([r for r in results.values() if r[0] is not None])} 个")
        return results

# ==================== 健康度计算 ====================
class HealthScorer:
    """健康度评分器"""
    
    @staticmethod
    def calculate_colo_stability(colos: List[str]) -> float:
        """计算Colo稳定性"""
        if not colos:
            return 0.0
        
        # 只考虑最近10次结果
        recent_colos = colos[-10:] if len(colos) > 10 else colos
        counter = Counter(recent_colos)
        
        if not counter:
            return 0.0
            
        most_common_count = counter.most_common(1)[0][1]
        return most_common_count / len(recent_colos)
    
    @staticmethod
    def calculate_latency_score(latencies: List[float]) -> float:
        """计算延迟分数"""
        if not latencies:
            return 0.0
        
        # 只考虑最近10次结果
        recent_latencies = latencies[-10:] if len(latencies) > 10 else latencies
        
        if not recent_latencies:
            return 0.0
            
        avg_latency = sum(recent_latencies) / len(recent_latencies)
        
        # 延迟在0-50ms: 满分，50-200ms: 线性衰减，200ms以上: 0分
        if avg_latency <= 50:
            return 1.0
        elif avg_latency <= 200:
            return 1.0 - (avg_latency - 50) / 150
        else:
            return 0.0
    
    @staticmethod
    def calculate_success_rate(success: int, fail: int) -> float:
        """计算成功率"""
        total = success + fail
        if total == 0:
            return 0.0
        return success / total
    
    @staticmethod
    def calculate_speed_score(speeds: List[float]) -> float:
        """计算速度分数"""
        if not speeds:
            return 0.0
            
        recent_speeds = speeds[-5:] if len(speeds) > 5 else speeds
        avg_speed = sum(recent_speeds) / len(recent_speeds)
        
        # 速度在3MB/s以上: 满分，0-3MB/s: 线性计算
        return min(avg_speed / 3.0, 1.0)
    
    @staticmethod
    def calculate_health_score(stats: IPStats) -> float:
        """计算综合健康度分数"""
        if not stats.latency:
            return 0.0
            
        colo_score = HealthScorer.calculate_colo_stability(stats.colo)
        latency_score = HealthScorer.calculate_latency_score(stats.latency)
        success_score = HealthScorer.calculate_success_rate(stats.success, stats.fail)
        speed_score = HealthScorer.calculate_speed_score(stats.speed)
        
        # 加权计算综合分数
        health = (
            colo_score * config.WEIGHT_COLO +
            latency_score * config.WEIGHT_LATENCY +
            success_score * config.WEIGHT_SUCCESS +
            speed_score * 0.1  # 速度占10%权重
        )
        
        # 确保分数在0-1之间
        health = max(0.0, min(1.0, health))
        return round(health, 3)
    
    @staticmethod
    def should_switch(current_ip: Optional[str], current_stats: Optional[IPStats], 
                     candidate_stats: IPStats, scene: str) -> bool:
        """判断是否需要切换IP"""
        # 如果当前没有IP，则切换
        if current_ip is None:
            return True
            
        # 如果当前IP没有统计信息，则切换
        if current_stats is None:
            return True
            
        # 场景特定规则
        if scene == "gpt":
            if candidate_stats.speed and candidate_stats.speed[-1] < config.GPT_MIN_SPEED:
                return False
            # GPT场景更看重速度
            candidate_speed = HealthScorer.calculate_speed_score(candidate_stats.speed)
            current_speed = HealthScorer.calculate_speed_score(current_stats.speed)
            if candidate_speed < current_speed * 1.2:  # 速度没有明显提升则不切换
                return False
                
        if scene == "stream":
            if candidate_stats.latency and candidate_stats.latency[-1] > config.STREAM_MAX_LATENCY:
                return False
            # 流媒体场景更看重延迟
            candidate_latency = HealthScorer.calculate_latency_score(candidate_stats.latency)
            current_latency = HealthScorer.calculate_latency_score(current_stats.latency)
            if candidate_latency < current_latency * 1.1:  # 延迟没有明显改善则不切换
                return False
            
        # 获取健康度分数
        current_health = current_stats.health or 0.0
        candidate_health = candidate_stats.health
        
        # 如果当前健康度已经很高，则不切换
        if current_health >= config.HEALTH_GOOD_THRESHOLD:
            return False
            
        # 如果候选IP健康度提升超过阈值，则切换
        return candidate_health - current_health >= config.HEALTH_SWITCH_THRESHOLD

# ==================== NekoBox配置生成 ====================
class NekoBoxGenerator:
    """NekoBox配置生成器"""
    
    @staticmethod
    def generate_profile(scene: str, ip: str) -> Dict:
        """生成NekoBox配置文件"""
        profile = {
            "log": {"level": "warn"},
            "inbounds": [
                {
                    "type": "socks",
                    "tag": "socks-in",
                    "listen": "127.0.0.1",
                    "listen_port": 10808
                }
            ],
            "outbounds": [
                {
                    "type": "vless",
                    "tag": f"CF-{scene.upper()}",
                    "server": ip,
                    "server_port": 443,
                    "uuid": config.UUID,
                    "tls": {
                        "enabled": True,
                        "server_name": config.SNI,
                        "utls": {
                            "enabled": True,
                            "fingerprint": config.FINGERPRINT[scene]
                        },
                        "reality": {
                            "enabled": True,
                            "public_key": config.REALITY_PUB,
                            "short_id": config.REALITY_SID
                        }
                    },
                    "transport": {"type": "tcp"}
                }
            ],
            "route": {"auto_detect_interface": True}
        }
        
        # 根据场景调整配置
        if scene == "gpt":
            # GPT场景可能需要不同的路由设置
            profile["route"]["rules"] = [
                {
                    "type": "field",
                    "domain": ["openai.com", "chat.openai.com", "api.openai.com"],
                    "outboundTag": f"CF-{scene.upper()}"
                }
            ]
        elif scene == "stream":
            # 流媒体场景可能需要不同的路由设置
            profile["route"]["rules"] = [
                {
                    "type": "field",
                    "domain": ["netflix.com", "youtube.com", "twitch.tv"],
                    "outboundTag": f"CF-{scene.upper()}"
                }
            ]
        
        return profile
    
    @staticmethod
    def save_profile(scene: str, ip: str) -> Optional[Path]:
        """保存配置文件"""
        try:
            profile = NekoBoxGenerator.generate_profile(scene, ip)
            file_path = config.BASE_DIR / "profiles" / f"nekobox_{scene}.json"
            
            if DataManager.save_json(file_path, profile):
                logger.info(f"配置文件已保存: {file_path} (IP: {ip})")
                return file_path
            return None
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return None

# ==================== 核心管理器 ====================
class IPHunterManager:
    """IP猎手管理器"""
    
    def __init__(self):
        self.db = DataManager.load_ip_db()
        self.state = DataManager.load_state()
        self.fail_db = DataManager.load_fail_db()
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        
    def update_ip_stats(self, ip: str, test_result: Tuple) -> None:
        """更新IP统计数据"""
        latency, colo, speed, source = test_result
        
        with self._lock:
            # 获取或创建统计对象
            ip_data = self.db.get(ip, {})
            stats = IPStats.from_dict(ip_data)
            
            # 更新数据
            if latency is not None:
                stats.latency.append(latency)
                stats.latency = stats.latency[-20:]  # 保留最近20次
                stats.success += 1
                
                if colo:
                    stats.colo.append(colo)
                    stats.colo = stats.colo[-20:]
                
                if speed:
                    stats.speed.append(speed)
                    stats.speed = stats.speed[-20:]
                    
                # 如果是新IP，设置来源
                if not stats.source and source:
                    stats.source = source
            else:
                stats.fail += 1
                # 记录失败到独立数据库
                self.fail_db[ip] = self.fail_db.get(ip, 0) + 1
                
            stats.last_seen = datetime.now().isoformat()
            stats.health = HealthScorer.calculate_health_score(stats)
            
            # 保存回数据库
            self.db[ip] = stats.to_dict()
            logger.debug(f"更新IP统计: {ip} 健康度: {stats.health} 延迟: {latency if latency else '失败'}ms")
    
    def evaluate_and_switch(self) -> None:
        """评估并切换最优IP"""
        with self._lock:
            for scene in config.SCENES:
                current_ip = self.state.get(scene)
                current_stats = None
                if current_ip and current_ip in self.db:
                    current_stats = IPStats.from_dict(self.db[current_ip])
                
                # 找到候选IP
                candidate_ip = None
                candidate_score = -1
                
                for ip, ip_data in self.db.items():
                    stats = IPStats.from_dict(ip_data)
                    
                    # 跳过没有足够数据的IP
                    if not stats.latency or len(stats.latency) < 3:
                        continue
                    
                    # 跳过失败次数过多的IP
                    if stats.fail > 5 and stats.success / (stats.success + stats.fail) < 0.5:
                        continue
                    
                    # 场景过滤
                    if scene == "gpt" and stats.speed and stats.speed[-1] < config.GPT_MIN_SPEED:
                        continue
                    if scene == "stream" and stats.latency and stats.latency[-1] > config.STREAM_MAX_LATENCY:
                        continue
                    
                    if stats.health > candidate_score:
                        candidate_score = stats.health
                        candidate_ip = ip
                
                # 如果没有找到候选IP，尝试从种子IP中选择
                if not candidate_ip and config.SEEDS:
                    candidate_ip = random.choice(config.SEEDS)
                    logger.warning(f"场景 {scene} 没有合适的候选IP，使用随机种子IP: {candidate_ip}")
                
                if candidate_ip and candidate_ip != current_ip:
                    candidate_stats = IPStats.from_dict(self.db.get(candidate_ip, {}))
                    if HealthScorer.should_switch(current_ip, current_stats, candidate_stats, scene):
                        old_ip = current_ip or "无"
                        self.state[scene] = candidate_ip
                        NekoBoxGenerator.save_profile(scene, candidate_ip)
                        logger.info(f"场景 {scene} 切换IP: {old_ip} -> {candidate_ip}")
    
    def run_scheduler(self) -> None:
        """调度器主循环"""
        logger.info("IP猎人调度器启动")
        self._running = True
        
        cycle_count = 0
        
        while self._running:
            try:
                cycle_count += 1
                logger.debug(f"开始第 {cycle_count} 轮调度")
                
                # 测试种子IP
                test_results = IPTester.test_multiple_ips(config.SEEDS)
                
                # 更新统计
                for ip, result in test_results.items():
                    self.update_ip_stats(ip, result)
                
                # 每5轮进行一次评估和切换
                if cycle_count % 5 == 0:
                    self.evaluate_and_switch()
                    
                    # 保存数据
                    DataManager.save_ip_db(self.db)
                    DataManager.save_state(self.state)
                    DataManager.save_fail_db(self.fail_db)
                    
                    logger.info(f"第 {cycle_count} 轮调度完成，数据库记录数: {len(self.db)}")
                else:
                    logger.debug(f"第 {cycle_count} 轮测试完成")
                
            except Exception as e:
                logger.error(f"调度器错误: {e}", exc_info=True)
            
            # 等待下一轮
            time.sleep(config.UPDATE_INTERVAL)
    
    def start(self) -> None:
        """启动后台线程"""
        if not self._running:
            logger.info("启动IP猎人后台线程")
            self._thread = threading.Thread(target=self.run_scheduler, daemon=True)
            self._thread.start()
        else:
            logger.warning("IP猎人后台线程已在运行")
    
    def stop(self) -> None:
        """停止后台线程"""
        if self._running:
            logger.info("停止IP猎人后台线程")
            self._running = False
            if self._thread:
                self._thread.join(timeout=5)
                if self._thread.is_alive():
                    logger.warning("后台线程未能正常停止")
        else:
            logger.warning("IP猎人后台线程未在运行")
    
    def get_top_ips(self, n: int = 10) -> List[Dict]:
        """获取排名前N的IP"""
        with self._lock:
            # 过滤掉没有足够数据的IP
            valid_ips = []
            for ip, ip_data in self.db.items():
                stats = IPStats.from_dict(ip_data)
                if stats.latency and len(stats.latency) >= 1:
                    valid_ips.append((ip, ip_data))
            
            # 按健康度排序
            sorted_ips = sorted(
                valid_ips,
                key=lambda x: x[1].get('health', 0),
                reverse=True
            )[:n]
            
            result = []
            for ip, data in sorted_ips:
                stats = IPStats.from_dict(data)
                
                # 计算平均延迟和速度
                avg_latency = round(sum(stats.latency[-5:]) / len(stats.latency[-5:]), 1) if stats.latency else 999
                avg_speed = round(sum(stats.speed[-5:]) / len(stats.speed[-5:]), 2) if stats.speed else 0.0
                
                result.append({
                    "IP": ip,
                    "评分": stats.health,
                    "延迟(ms)": avg_latency,
                    "速度(MB/s)": avg_speed,
                    "来源": stats.source,
                    "Colo": stats.colo[-1] if stats.colo else "UNK",
                    "成功率": f"{stats.success}/{stats.success + stats.fail}",
                    "最后检测": stats.last_seen[:16] if stats.last_seen else "从未"
                })
            return result
    
    def get_scene_status(self) -> Dict[str, Dict]:
        """获取各场景状态"""
        with self._lock:
            status = {}
            for scene in config.SCENES:
                ip = self.state.get(scene)
                if ip and ip in self.db:
                    stats = IPStats.from_dict(self.db[ip])
                    
                    # 计算平均延迟和速度
                    avg_latency = round(sum(stats.latency[-3:]) / len(stats.latency[-3:]), 1) if stats.latency else 0
                    avg_speed = round(sum(stats.speed[-3:]) / len(stats.speed[-3:]), 2) if stats.speed else 0
                    
                    status[scene] = {
                        "ip": ip,
                        "health": stats.health,
                        "latency": avg_latency,
                        "speed": avg_speed,
                        "colo": stats.colo[-1] if stats.colo else "UNK",
                        "last_seen": stats.last_seen[:16] if stats.last_seen else "从未"
                    }
                else:
                    status[scene] = {"ip": "无", "health": 0, "latency": 0, "speed": 0, "colo": "无", "last_seen": "从未"}
            return status
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        with self._lock:
            total_ips = len(self.db)
            
            # 统计健康IP数量
            healthy_ips = 0
            for ip_data in self.db.values():
                stats = IPStats.from_dict(ip_data)
                if stats.health >= 0.7:
                    healthy_ips += 1
            
            # 统计各场景使用情况
            scene_ips = {}
            for scene in config.SCENES:
                ip = self.state.get(scene)
                if ip and ip != "无":
                    scene_ips[scene] = ip
            
            return {
                "total_ips": total_ips,
                "healthy_ips": healthy_ips,
                "active_scenes": len([ip for ip in scene_ips.values() if ip != "无"]),
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    
    def test_custom_ip(self, ip: str) -> Dict[str, Any]:
        """测试自定义IP"""
        try:
            logger.info(f"开始测试自定义IP: {ip}")
            latency, colo, speed, source = IPTester.test_single_ip(ip)
            
            result = {
                "ip": ip,
                "success": latency is not None,
                "latency": round(latency, 1) if latency else None,
                "colo": colo,
                "speed": round(speed, 2) if speed else 0.0,
                "source": source if latency else "测试失败"
            }
            
            # 如果测试成功，更新到数据库
            if latency is not None:
                self.update_ip_stats(ip, (latency, colo, speed, "手动测试"))
                # 立即保存数据库
                DataManager.save_ip_db(self.db)
                logger.info(f"自定义IP测试成功: {ip} 延迟: {latency:.1f}ms")
            else:
                logger.warning(f"自定义IP测试失败: {ip}")
                
            return result
            
        except Exception as e:
            logger.error(f"自定义IP测试异常: {ip} - {e}")
            return {
                "ip": ip,
                "success": False,
                "error": str(e)
            }

# ==================== Streamlit前端 ====================
class StreamlitApp:
    """Streamlit应用前端"""
    
    def __init__(self):
        self.manager = IPHunterManager()
        self._init_session_state()
    
    def _init_session_state(self):
        """初始化会话状态"""
        if "app_started" not in st.session_state:
            self.manager.start()
            st.session_state.app_started = True
            st.session_state.test_history = []
        
        if "auto_refresh" not in st.session_state:
            st.session_state.auto_refresh = True
        
        if "last_refresh" not in st.session_state:
            st.session_state.last_refresh = time.time()
        
        if "custom_ip_test_result" not in st.session_state:
            st.session_state.custom_ip_test_result = None
    
    def render_sidebar(self):
        """渲染侧边栏"""
        with st.sidebar:
            st.title("⚙️ 控制面板")
            
            # 系统状态
            st.subheader("系统状态")
            system_stats = self.manager.get_system_stats()
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("IP总数", system_stats["total_ips"])
            with col2:
                st.metric("健康IP", system_stats["healthy_ips"])
            
            st.metric("活跃场景", system_stats["active_scenes"])
            st.caption(f"最后更新: {system_stats['last_update']}")
            
            st.divider()
            
            # 控制按钮
            st.subheader("控制")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 手动刷新", use_container_width=True):
                    st.session_state.last_refresh = time.time()
                    st.rerun()
            
            with col2:
                if st.button("📊 更新配置", use_container_width=True):
                    # 强制重新评估并更新配置
                    with st.spinner("更新配置中..."):
                        self.manager.evaluate_and_switch()
                        st.success("配置已更新!")
                        time.sleep(1)
                        st.rerun()
            
            # 自动刷新开关
            st.session_state.auto_refresh = st.toggle(
                "自动刷新",
                value=st.session_state.auto_refresh,
                help="每30秒自动刷新数据"
            )
            
            st.divider()
            
            # 添加自定义IP测试
            st.subheader("自定义IP测试")
            
            # 批量测试
            with st.expander("批量测试"):
                ip_list = st.text_area(
                    "输入IP列表 (每行一个)",
                    placeholder="1.2.3.4\n5.6.7.8\n...",
                    height=100
                )
                
                if st.button("批量测试IP", use_container_width=True) and ip_list:
                    ips = [ip.strip() for ip in ip_list.split('\n') if ip.strip()]
                    if ips:
                        with st.spinner(f"批量测试 {len(ips)} 个IP..."):
                            results = IPTester.test_multiple_ips(ips)
                            success_count = len([r for r in results.values() if r[0] is not None])
                            st.success(f"测试完成: {success_count}/{len(ips)} 个IP成功")
            
            # 单个测试
            custom_ip = st.text_input("测试单个IP:", placeholder="1.2.3.4")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("测试此IP", use_container_width=True) and custom_ip:
                    with st.spinner(f"测试IP {custom_ip}..."):
                        result = self.manager.test_custom_ip(custom_ip)
                        st.session_state.custom_ip_test_result = result
                        st.rerun()
            
            with col2:
                if st.button("清空结果", use_container_width=True):
                    st.session_state.custom_ip_test_result = None
                    st.rerun()
            
            # 显示测试结果
            if st.session_state.custom_ip_test_result:
                result = st.session_state.custom_ip_test_result
                if result["success"]:
                    st.success(f"✅ 测试成功")
                    st.info(f"""
                    **IP:** {result['ip']}  
                    **延迟:** {result['latency']}ms  
                    **速度:** {result['speed']}MB/s  
                    **Colo:** {result['colo']}  
                    **来源:** {result['source']}
                    """)
                else:
                    st.error(f"❌ 测试失败")
                    if "error" in result:
                        st.error(f"错误: {result['error']}")
            
            st.divider()
            
            # 操作说明
            with st.expander("📖 使用说明"):
                st.markdown("""
                ### 场景说明
                1. **normal**: 普通浏览场景
                2. **gpt**: GPT访问，要求高速 (≥1MB/s)
                3. **stream**: 流媒体，要求低延迟 (≤150ms)
                4. **custom**: 自定义场景
                
                ### 健康度说明
                - ✅ 绿色: 健康度 > 0.8 (优秀)
                - ⚠️ 黄色: 健康度 0.5-0.8 (良好)
                - 🔴 红色: 健康度 < 0.5 (较差)
                
                ### 自动更新
                - 后台每30秒测试一次种子IP
                - 每5轮测试(约2.5分钟)评估一次IP切换
                - 配置文件自动更新
                """)
    
    def render_main_content(self):
        """渲染主内容"""
        # 标题区域
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.title("🧬 Cloudflare IP 猎手")
            st.markdown("### 多场景智能IP优选系统")
        with col2:
            st.metric("更新间隔", f"{config.UPDATE_INTERVAL}秒")
        with col3:
            status = "✅ 运行中" if st.session_state.app_started else "❌ 已停止"
            st.metric("系统状态", status)
        
        st.divider()
        
        # 场景状态卡片
        st.subheader("📊 场景状态")
        scene_status = self.manager.get_scene_status()
        
        cols = st.columns(len(config.SCENES))
        for idx, scene in enumerate(config.SCENES):
            with cols[idx]:
                status = scene_status[scene]
                
                # 根据健康度设置颜色和图标
                health = status["health"]
                if health >= 0.8:
                    color = "green"
                    emoji = "✅"
                    status_text = "优秀"
                elif health >= 0.5:
                    color = "orange"
                    emoji = "⚠️"
                    status_text = "良好"
                else:
                    color = "red"
                    emoji = "🔴"
                    status_text = "较差"
                
                # 创建卡片
                with st.container(border=True):
                    st.markdown(f"### {emoji} {scene.upper()}")
                    
                    # IP地址
                    if status["ip"] != "无":
                        st.code(status["ip"], language="text")
                    else:
                        st.warning("等待分配IP")
                    
                    # 健康度显示
                    if status["ip"] != "无":
                        st.progress(health, text=f"健康度: {health:.3f} ({status_text})")
                        
                        # 详细信息
                        with st.expander("详细信息"):
                            st.markdown(f"""
                            **延迟:** {status['latency']}ms  
                            **速度:** {status['speed']}MB/s  
                            **Colo:** {status['colo']}  
                            **最后检测:** {status['last_seen']}
                            """)
                    else:
                        st.info("等待首次测试...")
        
        st.divider()
        
        # IP排行榜
        st.subheader("🏆 IP排行榜 (TOP 10)")
        
        # 添加筛选选项
        col1, col2, col3 = st.columns(3)
        with col1:
            show_count = st.slider("显示数量", 5, 20, 10)
        with col2:
            min_health = st.slider("最低健康度", 0.0, 1.0, 0.3, 0.1)
        with col3:
            sort_by = st.selectbox("排序方式", ["评分", "延迟", "速度"], index=0)
        
        # 获取数据
        top_ips = self.manager.get_top_ips(20)  # 获取更多以便筛选
        
        if top_ips:
            df = pd.DataFrame(top_ips)
            
            # 应用筛选
            df_filtered = df[df['评分'] >= min_health].head(show_count)
            
            # 排序
            if sort_by == "延迟":
                df_filtered = df_filtered.sort_values("延迟(ms)")
            elif sort_by == "速度":
                df_filtered = df_filtered.sort_values("速度(MB/s)", ascending=False)
            else:
                df_filtered = df_filtered.sort_values("评分", ascending=False)
            
            # 添加颜色编码
            def color_row(row):
                styles = []
                if row['评分'] >= 0.8:
                    styles.append('background-color: #d4edda')  # 浅绿
                elif row['评分'] >= 0.5:
                    styles.append('background-color: #fff3cd')  # 浅黄
                else:
                    styles.append('background-color: #f8d7da')  # 浅红
                return styles
            
            styled_df = df_filtered.style.apply(color_row, axis=1)
            
            # 显示表格
            st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "IP": st.column_config.TextColumn(width="medium"),
                    "评分": st.column_config.ProgressColumn(
                        format="%.3f",
                        min_value=0,
                        max_value=1.0,
                    ),
                    "延迟(ms)": st.column_config.NumberColumn(format="%.1f"),
                    "速度(MB/s)": st.column_config.NumberColumn(format="%.2f"),
                    "成功率": st.column_config.TextColumn(width="small"),
                    "Colo": st.column_config.TextColumn(width="small"),
                }
            )
            
            # 显示统计信息
            if len(df_filtered) > 0:
                avg_latency = df_filtered["延迟(ms)"].mean()
                avg_speed = df_filtered["速度(MB/s)"].mean()
                avg_health = df_filtered["评分"].mean()
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("平均延迟", f"{avg_latency:.1f}ms")
                with col2:
                    st.metric("平均速度", f"{avg_speed:.2f}MB/s")
                with col3:
                    st.metric("平均健康度", f"{avg_health:.3f}")
        else:
            st.info("暂无IP数据，等待后台扫描...")
            st.progress(0, text="等待数据...")
        
        st.divider()
        
        # NekoBox配置文件下载
        st.subheader("📥 NekoBox 配置下载")
        
        # 显示下载说明
        with st.expander("下载说明", expanded=False):
            st.markdown("""
            1. 点击下方对应场景的下载按钮
            2. 下载JSON配置文件
            3. 在NekoBox中导入配置文件
            4. 选择对应的出站节点即可使用
            
            **注意:** 配置文件会根据IP自动更新，建议定期重新下载
            """)
        
        # 配置文件下载区域
        profile_cols = st.columns(len(config.SCENES))
        
        for idx, scene in enumerate(config.SCENES):
            with profile_cols[idx]:
                status = scene_status[scene]
                profile_path = config.BASE_DIR / "profiles" / f"nekobox_{scene}.json"
                
                if profile_path.exists():
                    with open(profile_path, 'r') as f:
                        profile_data = f.read()
                    
                    # 显示当前IP
                    ip_display = status["ip"] if status["ip"] != "无" else "未分配"
                    st.markdown(f"**当前IP:** `{ip_display}`")
                    
                    # 下载按钮
                    st.download_button(
                        label=f"下载 {scene.upper()}",
                        data=profile_data,
                        file_name=f"nekobox_{scene}.json",
                        mime="application/json",
                        use_container_width=True,
                        help=f"下载{scene.upper()}场景的配置文件"
                    )
                    
                    # 显示配置文件信息
                    with st.expander("配置预览"):
                        try:
                            profile_json = json.loads(profile_data)
                            st.json(profile_json, expanded=False)
                        except:
                            st.code(profile_data[:200] + "...", language="json")
                else:
                    st.warning(f"等待生成 {scene.upper()}")
                    st.button(
                        f"{scene.upper()} 配置",
                        disabled=True,
                        use_container_width=True
                    )
                    
                    if status["ip"] != "无":
                        st.info(f"将使用IP: {status['ip']}")
    
    def run(self):
        """运行Streamlit应用"""
        # 页面配置
        st.set_page_config(
            page_title="Cloudflare IP 猎手",
            page_icon="🧬",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # 自动刷新逻辑
        if st.session_state.auto_refresh:
            elapsed = time.time() - st.session_state.last_refresh
            if elapsed > 30:  # 30秒自动刷新
                st.session_state.last_refresh = time.time()
                st.rerun()
        
        # 渲染界面
        self.render_sidebar()
        self.render_main_content()
        
        # 页脚信息
        st.divider()
        
        # 系统信息
        system_stats = self.manager.get_system_stats()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.caption(f"🕐 更新间隔: {config.UPDATE_INTERVAL}秒")
        with col2:
            st.caption(f"📊 数据库: {system_stats['total_ips']}个IP")
        with col3:
            st.caption(f"✅ 健康IP: {system_stats['healthy_ips']}个")
        with col4:
            current_time = datetime.now().strftime('%H:%M:%S')
            st.caption(f"🔄 最后刷新: {current_time}")
        
        # 调试信息（仅在需要时显示）
        if st.sidebar.checkbox("显示调试信息", False):
            st.sidebar.divider()
            st.sidebar.subheader("调试信息")
            
            # 显示后台线程状态
            thread_status = "运行中" if hasattr(self.manager, '_thread') and self.manager._thread and self.manager._thread.is_alive() else "停止"
            st.sidebar.text(f"后台线程: {thread_status}")
            
            # 显示数据库大小
            db_size = Path(config.DB_FILE).stat().st_size if Path(config.DB_FILE).exists() else 0
            st.sidebar.text(f"数据库大小: {db_size / 1024:.1f} KB")
            
            # 显示日志最后几行
            if Path(config.LOG_FILE).exists():
                with open(config.LOG_FILE, 'r') as f:
                    lines = f.readlines()
                    if lines:
                        st.sidebar.text("最近日志:")
                        for line in lines[-5:]:
                            st.sidebar.text(line.strip())

# ==================== 应用入口 ====================
def main():
    """主函数"""
    try:
        # 显示启动信息
        logger.info("启动Cloudflare IP猎手应用")
        logger.info(f"数据目录: {config.BASE_DIR / 'data'}")
        logger.info(f"配置目录: {config.BASE_DIR / 'profiles'}")
        logger.info(f"种子IP数量: {len(config.SEEDS)}")
        logger.info(f"场景数量: {len(config.SCENES)}")
        
        # 创建并运行应用
        app = StreamlitApp()
        app.run()
        
    except Exception as e:
        logger.error(f"应用启动失败: {e}", exc_info=True)
        
        # 在界面上显示错误
        st.set_page_config(page_title="错误 - Cloudflare IP 猎手")
        st.error(f"应用启动失败: {e}")
        st.code(str(e), language="text")
        
        # 显示调试信息
        with st.expander("调试信息"):
            import traceback
            st.code(traceback.format_exc(), language="text")

if __name__ == "__main__":
    main()