import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心 (请务必在此核对你的信息)
# ==========================================
CF_CONFIG = {
    "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm": "你的_Cloudflare_API_Token", 
    "7aa1c1ddfd9df2690a969d9f977f82ae": "你的_Zone_ID",
    "efc4c37be906c8a19a67808e51762c1f": "speed.milet.qzz.io",   # 必须是你在 CF 后台已经存在的 A 记录
}

# 你的 VLESS 链接列表
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
    # ... 粘贴更多 ...
]

# ==========================================
# 2. 自动化核心逻辑
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        self.token = str(config['api_token']).strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self.best_ip = "等待测速..."
        self.last_update = "尚未运行"
        self.status_log = []

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append(f"[{timestamp}] {message}")
        if len(self.status_log) > 12: self.status_log.pop(0)

    def update_cf_dns(self, ip):
        """核心修复：增加每一步的日志输出"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            self.log(f"🛰️ 正在从 CF 获取域名记录信息...")
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers, timeout=10).json()
            
            if not res.get("success"):
                self.log(f"❌ API 报错: {res.get('errors')[0].get('message')}")
                return False

            if not res["result"]:
                self.log(f"❌ 错误: CF 中不存在域名 {self.config['record_name']}")
                return False
            
            record = res["result"][0]
            record_id = record["id"]
            current_ip = record["content"]

            if current_ip == ip:
                self.log(f"✅ 当前 CF 记录已经是 {ip}，无需更新")
                return True

            self.log(f"🛠️ 发现新 IP，正在更新: {current_ip} -> {ip}")
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record_id}"
            data = {"type": "A", "name": self.config['record_name'], "content": ip, "ttl": 60, "proxied": False}
            put_res = requests.put(update_url, headers=self.headers, json=data, timeout=10).json()
            
            if put_res.get("success"):
                self.log(f"🚀 自动同步成功！")
                return True
            else:
                self.log(f"❌ 更新失败: {put_res.get('errors')[0].get('message')}")
                return False
        except Exception as e:
            self.log(f"⚠️ 网络或代码异常: {str(e)}")
            return False

    def run_loop(self):
        while True:
            self.log("🔄 开始自动优选巡检...")
            # 解析 IP
            ips = []
            for link in self.links:
                try:
                    p = urllib.parse.urlparse(link)
                    ips.append(p.netloc.split('@')[-1].split(':')[0])
                except: continue
            
            # 简单测速 (TCP 握手)
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
                self.log(f"🏆 锁定最优: {top_ip} ({results[0][1]}ms)")
                
                # 执行同步
                if self.update_cf_dns(top_ip):
                    self.best_ip = top_ip
                    self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                self.log("⚠️ 测速失败，未发现有效节点")
            
            self.log("💤 进入休眠，10分钟后再次运行")
            time.sleep(600)

# ==========================================
# 3. Streamlit UI
# ==========================================
def main():
    st.set_page_config(page_title="CF 优选监控", layout="centered")
    st.title("🛡️ 自动优选同步系统")

    if 'optimizer' not in st.session_state:
        st.session_state.optimizer = AutoOptimizer(CF_CONFIG, VLESS_LINKS)
        threading.Thread(target=st.session_state.optimizer.run_loop, daemon=True).start()

    opt = st.session_state.optimizer

    # 顶部指标
    c1, c2 = st.columns(2)
    c1.metric("当前生效 IP", opt.best_ip)
    c2.metric("最后同步", opt.last_update.split(" ")[-1] if " " in opt.last_update else "等待中")

    st.divider()

    # 日志输出
    st.subheader("⚙️ 运行日志")
    for msg in reversed(opt.status_log):
        if "❌" in msg or "⚠️" in msg: st.error(msg)
        elif "🚀" in msg or "✅" in msg: st.success(msg)
        else: st.code(msg)

    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()
