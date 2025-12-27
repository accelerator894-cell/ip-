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
    "max_workers": 15,
    "connect_timeout": 4.0,
    "download_timeout": 12.0,
    "geo_cache_hours": 6,
    "test_bytes_by_mode": {
        "☀️ 正常使用排位": 50_000,
        "⚡ 极速低延迟": 30_000,
        "🤖 GPT 独享专线": 100_000,
        "🎬 流媒体解锁专线": 200_000,
    }
}

GOLDEN_SUBNETS = [
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96", "172.67.69.1",
    "2a09:bac6:d69c:15f::23:4668"
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

def get_geo_info(ip: str, timeout=5.0) -> dict:
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
    def fill_crawler_pool(max_size=30):
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
                r = requests.get(url, timeout=20)
                ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)', r.text)
                for ip in ips:
                    if ip not in blacklist and ip not in found:
                        found.add(ip)
            except Exception as e:
                logger.warning(f"爬虫源 {url} 失败: {e}")
        new_list = list(found)[:max_size]
        safe_write_json(FILES["crawlers"], new_list)
        logger.info(f"爬虫池更新: {len(new_list)} 个")

    @staticmethod
    def fill_niche_pool(max_size=30):
        current = safe_json(FILES["niches"], [])
        if len(current) >= max_size: return
        blacklist = IPPoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_size * 10):
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

    logger.info("启动扫描 + 自动爬取 + 补位到10...")

    first_round_done = False
    min_nodes = 10

    while True:
        try:
            cfg = safe_json(FILES["config"], DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - time.time() % 300) < 10

            # 强制爬取（70% 概率）
            if random.random() < 0.7:
                threading.Thread(target=IPPoolManager.fill_crawler_pool).start()
                threading.Thread(target=IPPoolManager.fill_niche_pool).start()

            targets = []
            targets.extend({"ip": ip, "src": "⚡ 优质种子"} for ip in QUICK_SEEDS)

            if len(db) < min_nodes:
                if db:
                    sorted_db = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)
                    targets.extend({"ip": ip, "src": "🏆 已活节点"} for ip, _ in sorted_db)
                # 补位随机生成
                for _ in range(40):
                    net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                    candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                    if candidate not in db:
                        targets.append({"ip": candidate, "src": "💎 补位随机"})

            if first_round_done:
                targets.extend({"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(FILES["crawlers"], []))
                targets.extend({"ip": ip, "src": "💎 冷门"} for ip in safe_json(FILES["niches"], []))

            blacklist = IPPoolManager.get_blacklist()
            seen = set()
            unique_targets = [t for t in targets if t["ip"] not in blacklist and t["ip"] not in seen and not seen.add(t["ip"])]
            random.shuffle(unique_targets)

            workers = 8 if not first_round_done else cfg["max_workers"]

            results = []
            success_count = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                def test_ip(task):
                    nonlocal success_count
                    ip = task["ip"]
                    try:
                        with socket.socket() as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_ms = (time.perf_counter() - t1) * 1000

                        bytes_test = cfg["test_bytes_by_mode"].get(cfg["mode"], 50000)
                        speed = 0.0
                        try:
                            st = time.perf_counter()
                            r = requests.get(f"http://{ip}/__down?bytes={bytes_test}",
                                            headers={"Host": cfg["host"]},
                                            timeout=cfg["download_timeout"],
                                            stream=True)
                            size = 0
                            for chunk in r.iter_content(64 * 1024):
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
                            if fail_counts[ip] >= 10:
                                IPPoolManager.add_to_blacklist(ip)
                                logger.info(f"IP {ip} 失败10次，黑名单")

                        success_count += 1
                        return result
                    except Exception as e:
                        logger.debug(f"测试失败 {ip}: {e}")
                        fail_counts[ip] += 1
                        if fail_counts[ip] >= 10:
                            IPPoolManager.add_to_blacklist(ip)
                        return None

                futures = [executor.submit(test_ip, t) for t in unique_targets[:200]]
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

                if not first_round_done:
                    first_round_done = True
                    logger.info("第一轮完成，开始补位 + 自动进化")

            if len(db) < 10:
                logger.info(f"有效节点 {len(db)} 个，继续补位...")

            safe_write_json(FILES["database"], db)
            safe_write_json(FILES["fail_count"], dict(fail_counts))

        except Exception as e:
            logger.error(f"引擎异常: {e}")
            time.sleep(10)

        time.sleep(8)

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
        max_workers = st.slider("最大并发", 5, 30, cfg["max_workers"], step=5)

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
    st.info("引擎启动中... 正在补位到10个 + 自动爬取进化...")
    time.sleep(3)
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
    current_nodes = len(table_data)
    st.subheader(f"实时排行榜（策略：{data['mode']}） - 前 {display_count} 名"
                 f"（共 {current_nodes} 个有效节点 / 测试目标 {debug['targets']} → 成功 {debug['success']}）"
                 f"{' - 正在补位到10...' if current_nodes < 10 else ''}")

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

    st.caption(f"最后更新: {data['last_run']}　｜　每8秒刷新一次（自动爬取 + 优选替换中）")
    time.sleep(8)
    st.rerun()