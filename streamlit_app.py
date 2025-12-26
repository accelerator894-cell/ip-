import streamlit as st
import requests
import threading
import time
import urllib.parse
import base64
from datetime import datetime

# ==========================================
# 1. 配置中心 (请填入你的信息)
# ==========================================
CF_CONFIG = {
    "api_token": "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm", 
    "zone_id": "7aa1c1ddfd9df2690a969d9f977f82ae",
    "record_name": "speed.milet.qzz.io", 
}

# 外部订阅地址 (如果暂时没有，代码会使用下方默认的 VLESS_LINKS)
SUB_URL = "" 

# 初始备用节点列表
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
]

# ==========================================
# 2. 核心类逻辑 (封装 API 与 测速)
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.token = str(config.get("api_token", "")).strip()
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.best_ip = "尚未初始化"
        self.last_update = "等待中"
        self.status_log = []

    def log(self, message, type="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append({"time": timestamp, "msg": message, "type": type})
        if len(self.status_log) > 15: self.status_log.pop(0)

    def fetch_subscription(self):
        """动态同步订阅节点"""
        if not SUB_URL: return
        try:
            resp = requests.get(SUB_URL, timeout=10)
            decoded = base64.b64decode(resp.text).decode('utf-8')
            new_links = [line for line in decoded.split('\n') if line.strip().startswith("vless://")]
            if new_links:
                self.links = new_links
                self.log(f"🌐 订阅已更新，载入 {len(new_links)} 个节点", "success")
        except:
            self.log("⚠️ 订阅解析失败，保持原有列表", "error")

    def update_cf_dns(self, ip):
        """同步 IP 到 Cloudflare"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            self.log("🛰️ 正在从 Cloudflare 获取记录信息...", "info")
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            
            if not res.get("success"):
                self.log(f"❌ API 报错: {res['errors'][0]['message']}", "error")
                return False

            record = res["result"][0]
            if record["content"] == ip:
                self.log(f"✅ CF 记录已是 {ip}，无需操作", "success")
                return True

            self.log(f"🛠️ 发现更优 IP，开始同步: {ip}", "info")
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}"
            data = {"type": "A", "name": self.config['record_name'], "content": ip, "ttl": 60, "proxied": False}
            put_res = requests.put(update_url, headers=self.headers, json=data, timeout=10).json()
            
            if put_res.get("success"):
                self.log("🚀 同步成功！", "success")
                return True
            return False
        except Exception as e:
            self.log(f"⚠️ 异常: {str(e)}", "error")
            return False

    def run_forever(self):
        """自动化巡检主线程"""
        while True:
            self.fetch_subscription()
            self.log("🔄 开始新一轮自动优选...", "info")
            
            # 解析 IP
            ips = []
            for link in self.links:
                try:
                    p = urllib.parse.urlparse(link)
                    ips.append(p.netloc.split('@')[-1].split(':')[0])
                except: continue
            
            # 测速
            results = []
            for ip in set(ips):
                try:
                    start = time.time()
                    requests.get(f"https://{ip}", timeout=1.5, verify=False)
                    results.append((ip, int((time.time() - start) * 1000)))
                except: continue
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip = results[0][0]
                self.log(f"🏆 锁定最优 IP: {top_ip} ({results[0][1]}ms)", "info")
                if self.update_cf_dns(top_ip):
                    self.best_ip = top_ip
                    self.last_update = datetime.now().strftime("%H:%M:%S")
            
            self.log("💤 进入休眠周期 (10分钟)", "info")
            time.sleep(600)

# ==========================================
# 3. UI 界面层
# ==========================================
def main():
    st.set_page_config(page_title="CF 自动化管理", layout="centered")
    st.title("🛡️ 自动优选同步系统 v3.0")

    if 'opt' not in st.session_state:
        st.session_state.opt = AutoOptimizer(CF_CONFIG, VLESS_LINKS)
        threading.Thread(target=st.session_state.opt.run_forever, daemon=True).start()

    opt = st.session_state.opt

    col1, col2 = st.columns(2)
    col1.metric("当前生效 IP", opt.best_ip)
    col2.metric("最后更新", opt.last_update)

    st.divider()

    st.subheader("⚙️ 自动化实时日志")
    log_area = st.container(height=400, border=True)
    with log_area:
        for entry in reversed(opt.status_log):
            msg = f"[{entry['time']}] {entry['msg']}"
            if entry['type'] == "success": st.success(msg)
            elif entry['type'] == "error": st.error(msg)
            else: st.code(msg)

    time.sleep(10)
    st.rerun()

if __name__ == "__main__":
    main()
