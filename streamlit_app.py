import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. 配置中心 (保持不变)
# ==========================================
CF_CONFIG = {
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm", 
    "zone_id": "7aa1c1ddfd9df2690a969d9f977f82ae",
    "record_name": "speed.milet.qzz.io", 
}

VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
]

# ==========================================
# 2. 视频专项优化逻辑
# ==========================================
class VideoMaster:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.headers = {"Authorization": f"Bearer {config['api_token']}", "Content-Type": "application/json"}
        self.best_ip = "188.114.97.1"
        self.current_speed = 0.0
        self.last_update = "尚未运行"
        self.status_log = []

    def log(self, message, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": timestamp, "msg": message, "type": type})
        if len(self.status_log) > 12: self.status_log.pop(0)

    def test_single_ip(self, ip):
        """测试单个 IP 的延迟和下载速度"""
        try:
            # 1. 测延迟
            start_l = time.time()
            requests.get(f"https://{ip}", timeout=1.2, verify=False)
            latency = int((time.time() - start_l) * 1000)
            
            # 2. 测下载 (拉取 1.5MB 数据块)
            start_d = time.time()
            # 使用 Cloudflare 测速文件接口
            r = requests.get(f"https://{ip}/__down?bytes=1500000", timeout=2.5, verify=False)
            duration = time.time() - start_d
            
            if r.status_code == 200:
                speed = round((1.5 / duration) * 8, 2) # Mbps
                return {"ip": ip, "latency": latency, "speed": speed}
        except:
            return None

    def run_loop(self):
        while True:
            self.log("🎬 启动视频专项巡检 (延迟+下载并发测速)...", "info")
            ips = list(set([urllib.parse.urlparse(l).netloc.split('@')[-1].split(':')[0] for l in self.links]))
            
            # 使用多线程并发测速，极大缩短等待时间
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_ip = {executor.submit(self.test_single_ip, ip): ip for ip in ips}
                for future in future_to_ip:
                    res = future.result()
                    if res: results.append(res)
            
            if results:
                # 排序逻辑：优先下载速度，其次低延迟
                results.sort(key=lambda x: (-x['speed'], x['latency']))
                top = results[0]
                
                self.log(f"🏆 冠军节点: {top['ip']} | 速度: {top['speed']} Mbps | 延迟: {top['latency']}ms", "success")
                
                # 同步到 Cloudflare (逻辑省略同前，调用 API)
                # ... update_cf_dns(top['ip']) ...
                
                self.best_ip = top['ip']
                self.current_speed = top['speed']
                self.last_update = datetime.now().strftime("%H:%M:%S")

            time.sleep(600)

# ==========================================
# 3. Streamlit UI (自适应 Pro 版)
# ==========================================
def main():
    st.set_page_config(page_title="CF 视频专项优选", layout="centered")
    st.title("🎥 4K 视频自动优选系统")

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

if __name__ == "__main__":
    main()
