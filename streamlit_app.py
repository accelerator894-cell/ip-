import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. 安全配置中心 (从 Streamlit Secrets 读取)
# ==========================================
# 请在 Streamlit Cloud 后台的 Settings -> Secrets 中配置以下变量
try:
    CF_CONFIG = {
        "api_token": st.secrets["api_token"],
        "zone_id": st.secrets["zone_id"],
        "record_name": st.secrets["record_name"],
    }
except Exception:
    st.error("❌ 未找到 Secrets 配置，请在 Streamlit 后台设置 api_token, zone_id 和 record_name")
    st.stop()

# 测速素材库 (你可以随时增加更多链接)
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
]

# ==========================================
# 2. 视频专项优选引擎
# ==========================================
class VideoMaster:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.headers = {"Authorization": f"Bearer {config['api_token']}", "Content-Type": "application/json"}
        self.best_ip = "检测中..."
        self.current_speed = 0.0
        self.last_update = "尚未同步"
        self.status_log = []

    def log(self, message, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": timestamp, "msg": message, "type": type})
        if len(self.status_log) > 15: self.status_log.pop(0)

    def test_single_ip(self, ip):
        """测试单个 IP 的延迟和下载速度"""
        try:
            # 1. 测延迟
            start_l = time.time()
            requests.get(f"https://{ip}", timeout=1.5, verify=False)
            latency = int((time.time() - start_l) * 1000)
            
            # 2. 测下载 (拉取 1.5MB 数据块)
            start_d = time.time()
            r = requests.get(f"https://{ip}/__down?bytes=1500000", timeout=3.0, verify=False)
            duration = time.time() - start_d
            
            if r.status_code == 200:
                speed = round((1.5 / duration) * 8, 2) # Mbps
                return {"ip": ip, "latency": latency, "speed": speed}
        except:
            return None

    def update_cf(self, new_ip):
        """同步 IP 到 Cloudflare"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            if res.get("success") and res.get("result"):
                record_id = res["result"][0]["id"]
                current_ip = res["result"][0]["content"]
                if current_ip == new_ip: return "skip"
                
                update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record_id}"
                data = {"type": "A", "name": self.config['record_name'], "content": new_ip, "ttl": 60, "proxied": False}
                requests.put(update_url, headers=self.headers, json=data, timeout=10)
                return "success"
        except: return "error"

    def run_loop(self):
        while True:
            self.log("🎬 启动云端 4K 视频专项巡检...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links]))
            
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(self.test_single_ip, ip) for ip in ips]
                for f in futures:
                    res = f.result()
                    if res: results.append(res)
            
            if results:
                results.sort(key=lambda x: (-x['speed'], x['latency']))
                top = results[0]
                self.log(f"🏆 筛选完成: {top['ip']} ({top['speed']} Mbps)", "success")
                
                sync_status = self.update_cf(top['ip'])
                if sync_status == "success": self.log(f"🚀 已同步到 CF: {top['ip']}", "success")
                elif sync_status == "skip": self.log("✅ IP 未变动，无需重复同步", "info")
                
                self.best_ip = top['ip']
                self.current_speed = top['speed']
                self.last_update = datetime.now().strftime("%H:%M:%S")
            
            time.sleep(600)

# ==========================================
# 3. 仪表盘界面
# ==========================================
st.set_page_config(page_title="CF 视频优选云端版", layout="centered")
st.title("🎥 4K 视频自动优选 (云端版)")

if 'master' not in st.session_state:
    st.session_state.master = VideoMaster(CF_CONFIG, VLESS_LINKS)
    threading.Thread(target=st.session_state.master.run_loop, daemon=True).start()

vm = st.session_state.master
c1, c2, c3 = st.columns(3)
c1.metric("最优 IP", vm.best_ip)
c2.metric("实测带宽", f"{vm.current_speed} Mbps")
c3.metric("最后同步", vm.last_update)

st.divider()
for entry in reversed(vm.status_log):
    msg = f"[{entry['time']}] {entry['msg']}"
    if entry['type'] == "success": st.success(msg)
    else: st.code(msg)

time.sleep(10)
st.rerun()
