import streamlit as st
import requests
import time
import re
import random
import os
import pandas as pd
from datetime import datetime

# --- 1. 页面配置 ---
st.set_page_config(page_title="4K 引擎：两仪式限定版", page_icon="🗡️", layout="wide")

# ===========================
# 🎨 UI 魔改核心区域 (CSS注入)
# ===========================
# 这里的图片链接来自于网络公开资源，如果失效，请替换为你自己的图片链接（图床或GitHub原始链接）
BG_IMAGE_URL = "https://i.pinimg.com/originals/f4/32/23/f432238497920c075c7981a5f3e6e752.jpg" # 全屏背景壁纸
SIDEBAR_BG_URL = "https://w.wallhaven.cc/full/lq/wallhaven-lqg752.jpg" # 侧边栏顶部装饰图

st.markdown(f"""
    <style>
    /* 隐藏默认元素 */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}

    /* 🌟 全局背景设置 */
    .stApp {{
        background-image: url("{BG_IMAGE_URL}");
        background-size: cover;
        background-position: center center;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }}

    /* 🌑 内容区域容器 - 半透明深色蒙版 */
    .block-container {{
        background-color: rgba(20, 20, 25, 0.85); /* 深色半透明背景 */
        border-radius: 15px;
        border: 2px solid #8B0000; /* 深红色边框 */
        padding: 2rem;
        margin-top: 2rem;
        box-shadow: 0 0 20px rgba(139, 0, 0, 0.5); /* 红色光晕 */
    }}

    /* 🗡️ 侧边栏美化 */
    [data-testid="stSidebar"] {{
        background-color: rgba(40, 10, 10, 0.9); /* 深红黑色背景 */
        border-right: 2px solid #8B0000;
    }}
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
        color: #FF6B6B !important; /* 侧边栏标题粉红色 */
        font-family: 'serif';
    }}
    [data-testid="stSidebarUserContent"] {{
        color: #E0E0E0; /* 侧边栏文字颜色 */
    }}

    /* 🩸 标题与文字风格 */
    h1, h2, h3 {{
        color: #FF3333 !important; /* 主标题鲜红色，致敬直死之魔眼 */
        text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        font-family: 'serif'; /* 尝试使用衬线体增加优雅感 */
        font-weight: bold;
    }}
    p, .stMarkdown, li {{
        color: #E0E0E0 !important; /* 正文亮白色 */
        font-weight: 500;
    }}
    .stCaption {{
        color: #A0A0A0 !important;
    }}

    /* 📊 组件风格定制 */
    /* Metric 指标卡片 */
    [data-testid="stMetricValue"] {{
        color: #FF3333 !important;
    }}
    [data-testid="stMetricLabel"] {{
        color: #E0E0E0 !important;
    }}
    div[data-testid="metric-container"] {{
        background-color: rgba(139, 0, 0, 0.2);
        border: 1px solid #8B0000;
        padding: 10px;
        border-radius: 8px;
    }}

    /* DataFrame 表格 */
    [data-testid="stDataFrame"] {{
        border: 1px solid #8B0000;
        border-radius: 5px;
        overflow: hidden;
    }}
    
    /* Tabs 标签页 */
    .stTabs [data-baseweb="tab-list"] {{ gap: 8px; }}
    .stTabs [data-baseweb="tab"] {{
        height: 45px;
        background-color: rgba(60, 20, 20, 0.7);
        color: #E0E0E0;
        border-radius: 5px;
        border: 1px solid #5c1a1a;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: #8B0000 !important; /* 选中状态深红色 */
        color: white !important;
        font-weight: bold;
        border: 1px solid #ff3333;
    }}
    
    /* 成功/信息提示框 */
    .stAlert {{
        background-color: rgba(20, 20, 20, 0.8);
        color: white;
        border: 1px solid #8B0000;
    }}
    </style>
    """, unsafe_allow_html=True)
# ===========================
# UI 魔改结束
# ===========================


# --- 2. 配置读取 ---
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"].strip(),
        "zone_id": st.secrets["zone_id"].strip(),
        "record_name": st.secrets["record_name"].strip(),
    }
except Exception as e:
    st.error(f"❌ 配置读取失败: {e}")
    st.stop()

DB_FILE = "best_ip_history.txt"

# --- 3. 核心功能函数 (保持不变，性能最优化) ---

def check_api_health():
    """优先检测 API 健康度"""
    try:
        url = "https://api.cloudflare.com/client/v4/user/tokens/verify"
        headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
        resp = requests.get(url, headers=headers, timeout=2).json()
        if resp.get("success"):
            return True, "🟢 API 状态：正常 (连接确立)"
        else:
            return False, f"🔴 权限错误: {resp['errors'][0]['message']}"
    except:
        return False, "🟡 网络连接超时"

def get_ip_info(ip):
    """查询 IP 地理位置"""
    try:
        url = f"http://ip-api.com/json/{ip}?fields=countryCode,country"
        r = requests.get(url, timeout=1.5).json()
        cc = r.get("countryCode", "UNK")
        country = r.get("country", "Unknown")
        
        region = "🌍 其他"
        if cc in ['CN', 'HK', 'TW', 'JP', 'KR', 'SG', 'MY', 'TH', 'VN', 'IN', 'ID', 'PH']:
            region = "🌏 亚洲"
        elif cc in ['US', 'CA', 'MX', 'BR', 'AR', 'CL']:
            region = "🇺🇸 美洲"
        elif cc in ['DE', 'GB', 'FR', 'NL', 'RU', 'IT', 'ES', 'PL', 'UA', 'TR']:
            region = "🇪🇺 欧洲"
            
        return region, country
    except:
        return "🛸 未知", "Unknown"

def get_global_ips():
    sources = ["https://raw.githubusercontent.com/Alvin9999/new-pac/master/cloudflare.txt"]
    pool = set()
    try:
        r = requests.get(sources[0], timeout=3)
        found = re.findall(r'(?:\d{1,3}\.){3}\d{1,3}', r.text)
        pool.update(found)
    except: pass
    return random.sample(list(pool), min(len(pool), 15))

def fast_ping(ip):
    try:
        start = time.time()
        requests.head(f"http://{ip}", headers={"Host": CF_CONFIG['record_name']}, timeout=1.0)
        return int((time.time() - start) * 1000)
    except:
        return 9999

def check_netflix(ip):
    try:
        r = requests.get(f"http://{ip}/title/80018499", headers={"Host": "www.netflix.com"}, timeout=1.5)
        return "✅" if r.status_code in [200, 301, 302] else "❌"
    except: return "❓"

def sync_dns(new_ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{CF_CONFIG['zone_id']}/dns_records"
    headers = {"Authorization": f"Bearer {CF_CONFIG['api_token']}"}
    try:
        params = {"name": CF_CONFIG['record_name'], "type": "A"}
        search = requests.get(url, headers=headers, params=params, timeout=5).json()
        
        if not search.get("success") or not search.get("result"):
            return "❌ 未找到 A 记录"
            
        record = search["result"][0]
        if record["content"] == new_ip:
            return "✅ 解析已是最新状态"
            
        update = requests.put(f"{url}/{record['id']}", headers=headers, json={
            "type": "A", "name": CF_CONFIG['record_name'], "content": new_ip, "ttl": 60, "proxied": False
        }).json()
        
        return f"🚀 同步成功，境界已更新 -> {new_ip}" if update.get("success") else "❌ 更新失败"
    except Exception as e: return f"⚠️ 异常: {e}"

# --- 4. 主界面逻辑 ---

# 主标题，增加装饰
st.markdown("# 🗡️ 4K 引擎：直死之魔眼")

# 侧边栏：加入装饰图和状态
with st.sidebar:
    # 侧边栏顶部装饰图
    st.image(SIDEBAR_BG_URL, use_column_width=True)
    st.markdown("---")
    st.header("⚙️ 境界监控")
    
    is_ok, status_msg = check_api_health()
    if is_ok:
        st.success(status_msg)
    else:
        st.error(status_msg)
    
    st.divider()
    if st.button("🗑️ 清理历史痕迹"):
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        st.rerun()

# 主运行区
with st.spinner("🌙 正在于暗夜中巡视全球节点..."):
    results = []
    base_ips = ["108.162.194.1", "108.162.192.5", "172.64.32.12", "162.159.61.1"]
    global_ips = get_global_ips()
    
    candidates = base_ips + global_ips
    valid_nodes = []
    
    for ip in candidates:
        lat = fast_ping(ip)
        if lat < 500:
            valid_nodes.append({"ip": ip, "lat": lat, "type": "🏠 专属" if ip in base_ips else "🌍 搜集"})
    
    final_data = []
    if valid_nodes:
        valid_nodes.sort(key=lambda x: x['lat'])
        top_nodes = valid_nodes[:8] 
        
        for node in top_nodes:
            reg, ctry = get_ip_info(node['ip'])
            nf = check_netflix(node['ip']) if node['lat'] < 200 else "❓"
            node.update({"region": reg, "country": ctry, "nf": nf})
            final_data.append(node)
            
        winner = final_data[0]
        
        # 冠军展示，增加一点中二气息
        st.success(f"🩸 已捕捉到最优节点: {winner['ip']} ({winner['region']}) | 延迟: {winner['lat']}ms")
        st.info(sync_dns(winner['ip']))
        
        # --- 分区展示 ---
        st.subheader("📊 境界观测看板")
        
        df = pd.DataFrame(final_data)
        cols_map = {"ip": "IP地址", "region": "区域", "country": "国家", "lat": "延迟", "nf": "解锁", "type": "来源"}
        df_show = df[["ip", "region", "country", "lat", "nf", "type"]].rename(columns=cols_map)
        
        tab1, tab2, tab3, tab4 = st.tabs(["🌐 全观测", "🌏 亚洲区", "🇺🇸 美洲区", "🇪🇺 欧洲区"])
        
        with tab1: st.dataframe(df_show, use_container_width=True, hide_index=True)
        with tab2: 
            d = df_show[df_show["区域"]=="🌏 亚洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("此区域暂无反应")
        with tab3:
            d = df_show[df_show["区域"]=="🇺🇸 美洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("此区域暂无反应")
        with tab4:
            d = df_show[df_show["区域"]=="🇪🇺 欧洲"]
            if not d.empty: st.dataframe(d, use_container_width=True, hide_index=True)
            else: st.caption("此区域暂无反应")

        # 历史记录
        with open(DB_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%H:%M')} | {winner['ip']} | {winner['region']} | {winner['lat']}ms\n")
            
        if os.path.exists(DB_FILE):
            st.divider()
            with st.expander("📜 过往观测记录"):
                with open(DB_FILE, "r") as f: st.text("".join(f.readlines()[-10:]))
                
    else:
        st.warning("⚠️ 本轮巡视未发现可用节点")

st.caption(f"🕒 上次观测时间: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(600)
st.rerun()
