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
import queue             # ← 新增
from collections import deque  # ← 新增

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
#         常量 & 配置升级
# ==============================
RESULT_FILE = "scan_results.json"
DB_FILE     = "ip_database.json"
CRAWLER_FILE = "crawler_pool.json"
NICHE_FILE   = "niche_pool.json"
CONFIG_FILE  = "app_config.json"
STATS_FILE   = "daily_stats.json"           # ← 新增：用于记录历史表现曲线

# 更多的优质网段（2024-2025 常用）
GOLDEN_SUBNETS = [
    "104.16.0.0/12", "104.28.0.0/16", "104.21.0.0/16",
    "172.64.0.0/13", "172.67.0.0/16", "162.158.0.0/15",
    "173.245.48.0/20", "188.114.96.0/20", "190.93.240.0/20",
]

QUICK_SEEDS = [
    "104.19.19.19", "172.64.198.1", "104.19.112.1", "172.67.1.1",
    "104.18.20.126", "172.64.155.1", "104.16.123.96"   # ← 增加一些常用备选
]

# ==============================
#         增强型配置结构
# ==============================
DEFAULT_CONFIG = {
    "mode": "☀️ 正常使用排位",
    "host": "speed.cloudflare.com",
    "port": 443,
    "uuid": "",
    "ws_path": "/",
    "test_bytes": {          # ← 按策略自动调整测试流量
        "☀️ 正常使用排位": 200000,
        "⚡ 极速低延迟": 80000,
        "🤖 GPT 独享专线": 150000,
        "🎬 流媒体解锁专线": 300000,
    },
    "max_workers": 35,       # 可由用户微调
    "connect_timeout": 0.45,
    "download_timeout": 1.8,
    "geo_cache_hours": 4,    # IP-API 缓存有效期
}

# ==============================
#         工具函数
# ==============================
def safe_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def safe_write_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except:
        pass


# ==============================
#    更好的爬虫池&冷门挖掘（加入黑名单机制）
# ==============================
class PoolManager:
    BLACKLIST_FILE = "blacklist_ips.json"
    
    @classmethod
    def get_blacklist(cls):
        return set(safe_json(cls.BLACKLIST_FILE, []))

    @classmethod
    def add_to_blacklist(cls, ip):
        bl = cls.get_blacklist()
        bl.add(ip)
        safe_write_json(cls.BLACKLIST_FILE, list(bl))

    @staticmethod
    def fill_crawler(max_count=25):
        ips = safe_json(CRAWLER_FILE, [])
        if len(ips) >= max_count:
            return

        sources = [
            "https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt",
            "https://cfip.shodan.uk/",
            "https://api.chaoming.cc/cfip",
        ]

        found = set(ips)
        blacklist = PoolManager.get_blacklist()

        for url in sources:
            try:
                r = requests.get(url, timeout=4)
                if r.status_code != 200:
                    continue
                new_ips = re.findall(r'(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)', r.text)
                found.update(ip for ip in new_ips if ip not in blacklist)
            except:
                continue

        random.shuffle(list(found))
        safe_write_json(CRAWLER_FILE, list(found)[:max_count])

    @staticmethod
    def fill_niche(max_count=25):
        ips = safe_json(NICHE_FILE, [])
        if len(ips) >= max_count:
            return

        blacklist = PoolManager.get_blacklist()
        new_ips = []
        for _ in range(max_count * 3):
            try:
                net = ipaddress.ip_network(random.choice(GOLDEN_SUBNETS))
                candidate = str(net.network_address + random.randint(1, net.num_addresses - 3))
                if candidate not in blacklist:
                    new_ips.append(candidate)
            except:
                continue

        ips = list(set(ips + new_ips))[:max_count]
        safe_write_json(NICHE_FILE, ips)


# ==============================
#         结果缓存 + 历史曲线（每天简单统计）
# ==============================
class StatsRecorder:
    @staticmethod
    def record_top_ip(ip, score, speed, delay):
        today = datetime.now().strftime("%Y-%m-%d")
        stats = safe_json(STATS_FILE, {})

        if today not in stats:
            stats[today] = []

        stats[today].append({
            "time": datetime.now().strftime("%H:%M"),
            "ip": ip,
            "score": score,
            "speed": speed,
            "delay": delay
        })

        # 保留最近 14 天
        keep_days = 14
        dates = sorted(stats.keys(), reverse=True)[:keep_days]
        stats = {k: stats[k] for k in dates}

        safe_write_json(STATS_FILE, stats)


# ==============================
#         主进化引擎 - 重大优化版本
# ==============================
def background_evolution():
    db = safe_json(DB_FILE, {})
    geo_cache = {}          # ip -> (countryCode, country, expire)
    result_queue = queue.Queue(maxsize=100)
    last_full_scan = 0
    start_time = time.time()

    def get_geo(ip):
        now = time.time()
        if ip in geo_cache:
            cc, country, exp = geo_cache[ip]
            if exp > now:
                return {"cc": cc, "country": country}
        try:
            r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode,country", timeout=1.2)
            d = r.json()
            if d.get("status") == "success":
                geo_cache[ip] = (d["countryCode"], d["country"], now + 3600 * DEFAULT_CONFIG["geo_cache_hours"])
                return {"cc": d["countryCode"], "country": d["country"]}
        except:
            pass
        return {"cc": "??", "country": "未知"}

    while True:
        try:
            cfg = safe_json(CONFIG_FILE, DEFAULT_CONFIG.copy())
            now = time.time()
            is_full_scan = (now - last_full_scan >= 300)

            # 目标收集策略（分层）
            candidates = []

            if is_full_scan:
                last_full_scan = now
                candidates += [{"ip": ip, "src": "📂 全量基因普查"} for ip in db]
            else:
                # 1. 固定优质种子
                candidates += [{"ip": ip, "src": "⚡ 固定种子"} for ip in QUICK_SEEDS]
                # 2. 历史 Top 20~30
                if now - start_time > 12:
                    top = sorted(db.items(), key=lambda x: x[1].get('score', 0), reverse=True)[:30]
                    candidates += [{"ip": ip, "src": "🏆 历史排行"} for ip, _ in top]
                # 3. 爬虫 + 冷门
                if now - start_time > 6:
                    candidates += [{"ip": ip, "src": "🕷️ 爬虫"} for ip in safe_json(CRAWLER_FILE, [])]
                    candidates += [{"ip": ip, "src": "💎 冷门挖掘"} for ip in safe_json(NICHE_FILE, [])]

            # 去重 + 过滤黑名单
            blacklist = PoolManager.get_blacklist()
            seen = set()
            targets = []
            for c in candidates:
                ip = c["ip"]
                if ip in blacklist or ip in seen:
                    continue
                seen.add(ip)
                targets.append(c)

            random.shuffle(targets)  # 打乱降低头部效应

            # ==============================
            #  并发测试（带结果队列 + 动态限流）
            # ==============================
            max_workers = cfg.get("max_workers", 35)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                def test_one(t):
                    ip = t["ip"]
                    try:
                        # 1. 快速 TCP ping
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(cfg["connect_timeout"])
                            t1 = time.perf_counter()
                            s.connect((ip, cfg["port"]))
                            tcp_latency = (time.perf_counter() - t1) * 1000
                    except:
                        return None

                    # 2. 下载测速
                    down_bytes = cfg["test_bytes"].get(cfg["mode"], 200000)
                    speed = 0.0
                    try:
                        st_t = time.perf_counter()
                        r = requests.get(
                            f"http://{ip}/__down?bytes={down_bytes}",
                            headers={"Host": cfg["host"]},
                            timeout=cfg["download_timeout"],
                            stream=True
                        )
                        size = 0
                        for chunk in r.iter_content(64*1024):
                            size += len(chunk)
                            if time.perf_counter() - st_t > 1.8:
                                break
                        speed = size / (time.perf_counter() - st_t) / 1024 / 1024
                    except:
                        pass

                    geo = get_geo(ip)

                    # 评分公式（可按模式微调权重）
                    score = round(100 - tcp_latency/4 + min(speed * 6, 45), 1)

                    result = {
                        "ip": ip,
                        "score": score,
                        "avg": round(tcp_latency, 1),
                        "speed": round(speed, 2),
                        "src": t["src"],
                        "cc": geo["cc"],
                        "country": geo["country"],
                        "last_test": datetime.now().strftime("%H:%M:%S")
                    }

                    # 更新数据库（只在更好时更新，也可设置阈值）
                    old = db.get(ip, {})
                    if score > old.get("score", 0) - 3:  # 允许小幅波动也更新
                        db[ip] = result

                    # 记录到统计（只记录前3名）
                    if score > 85:
                        StatsRecorder.record_top_ip(ip, score, speed, tcp_latency)

                    return result

                futures = [executor.submit(test_one, t) for t in targets[:120]]  # 一次最多测120个

                current_batch = []
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    if res:
                        current_batch.append(res)
                        # 实时保存top结果（给前端看）
                        if len(current_batch) >= 3:
                            sorted_batch = sorted(current_batch, key=lambda x: x["score"], reverse=True)
                            safe_write_json(RESULT_FILE, {
                                "last_run": datetime.now().strftime("%H:%M:%S"),
                                "winner": sorted_batch[0],
                                "table": sorted_batch[:50],  # 前50展示
                                "is_full": is_full_scan,
                                "mode": cfg["mode"]
                            })
                            current_batch = current_batch[-20:]  # 保留尾部用于后续合并

            # 周期性补充池子
            if random.random() < 0.4:
                threading.Thread(target=PoolManager.fill_crawler, daemon=True).start()
                threading.Thread(target=PoolManager.fill_niche, daemon=True).start()

            safe_write_json(DB_FILE, db)

        except Exception as e:
            # print("后台循环异常:", e)  # 调试用，可注释
            pass

        time.sleep(8)  # 主循环间隔


# 启动后台引擎
if "evolution_engine_started" not in st.session_state:
    threading.Thread(target=background_evolution, daemon=True).start()
    st.session_state.evolution_engine_started = True


# ==============================
#           前端部分（基本保持原样，可按需微调）
# ==============================
st.set_page_config(page_title="Cloudflare 猎手进化版", page_icon="🧬", layout="wide")

# 侧边栏（可再增加一些高级选项）
with st.sidebar:
    st.markdown("### 🛠️ 配置控制台")
    cfg = safe_json(CONFIG_FILE, DEFAULT_CONFIG.copy())

    modes = list(DEFAULT_CONFIG["test_bytes"].keys())
    mode_idx = modes.index(cfg["mode"]) if cfg["mode"] in modes else 0
    new_mode = st.radio("优选策略", modes, index=mode_idx)

    with st.expander("🔧 高级参数", expanded=False):
        new_host = st.text_input("伪装域名", value=cfg["host"])
        new_port = st.number_input("端口", 80, 65535, cfg["port"])
        new_uuid = st.text_input("UUID", value=cfg.get("uuid", ""))
        new_path = st.text_input("WS路径", value=cfg.get("ws_path", "/"))
        max_workers = st.slider("最大并发数", 10, 80, cfg.get("max_workers", 35))

    if st.button("💾 保存并重启引擎", type="primary"):
        new_cfg = cfg.copy()
        new_cfg.update({
            "mode": new_mode,
            "host": new_host,
            "port": new_port,
            "uuid": new_uuid,
            "ws_path": new_path,
            "max_workers": max_workers,
        })
        safe_write_json(CONFIG_FILE, new_cfg)
        if os.path.exists(RESULT_FILE):
            os.remove(RESULT_FILE)
        st.toast("配置已保存，引擎即将重启...", icon="✅")
        time.sleep(0.8)
        st.rerun()

    st.caption("ℹ️  后台自动进化中...  无需手动干预")

# 主界面 =============================================

data = safe_json(RESULT_FILE, None)

if data is None:
    st.title("🧬 Cloudflare 猎手进化版")
    st.info("正在启动进化引擎... 初次加载约需 10~25 秒\n\n请稍候...")
    time.sleep(3)
    st.rerun()
else:
    winner = data["winner"]
    st.title("🧬 Cloudflare 猎手进化版")

    tag = "🚀 全量基因扫描" if data.get("is_full") else "⚡ 实时监控优化"
    st.markdown(f"### 🏆 当前最强节点：`{winner['ip']}`　|　{tag}")

    cols = st.columns([2,1,1,1])
    with cols[0]:
        st.metric("综合进化分", f"{winner['score']:.1f}", help="延迟+速度综合评分")
    with cols[1]:
        st.metric("TCP延迟", f"{winner['avg']:.1f} ms")
    with cols[2]:
        st.metric("下载速度", f"{winner['speed']:.2f} MB/s")
    with cols[3]:
        st.metric("地区", f"{winner['cc']} {winner['country']}")

    st.divider()

    st.subheader(f"基因库实时排行榜（策略：{data['mode']}）")

    df = pd.DataFrame(data["table"])

    df["标记"] = df["src"].replace({
        "⚡ 固定种子": "⚡ 优质种子",
        "🏆 历史排行": "🏆 历史最优",
        "🕷️ 爬虫": "🕷️ 网络爬取",
        "💎 冷门挖掘": "💎 珍稀挖掘",
        "📂 全量基因普查": "📂 全库扫描"
    })

    df["地区"] = df["cc"] + " " + df["country"]

    st.dataframe(
        df,
        column_order=["score", "标记", "ip", "地区", "avg", "speed", "last_test"],
        column_config={
            "score": st.column_config.ProgressColumn("评分", min_value=0, max_value=130, format="%d"),
            "avg": st.column_config.NumberColumn("延迟 ms", format="%.1f"),
            "speed": st.column_config.NumberColumn("速度 MB/s", format="%.2f"),
        },
        hide_index=True,
        use_container_width=True
    )

    st.caption(f"数据更新于 {data['last_run']}　|　每5分钟进行一次全量扫描")

    # 自动刷新（可调）
    time.sleep(4.5)
    st.rerun()