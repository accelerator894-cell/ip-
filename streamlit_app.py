import streamlit as st
import requests
import threading
import time
import urllib.parse
from datetime import datetime

# ==========================================
# 1. 配置中心 (请务必检查此处是否有空格)
# ==========================================
CF_CONFIG = {
    "92os9FwyeG7jQDYpD6Rb0Cxrqu5YjtUjGfY1xKBm": "你的_Cloudflare_API_Token", # 确保没有前后空格
    "7aa1c1ddfd9df2690a969d9f977f82ae": "你的_Zone_ID",
    "efc4c37be906c8a19a67808e51762c1f": "speed.milet.qzz.io",   # 目标二级域名
}

# 你的 VLESS 链接库
VLESS_LINKS = [
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@162.159.136.0:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@188.114.97.1:443/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp",
    "vless://26da6cf2-7c72-456a-a3d8-56abe6b7c0e6@141.101.120.5:2053/?type=ws&encryption=none&flow=&host=milet.qzz.io&path=%2F&security=tls&sni=milet.qzz.io&fp=chrome&packetEncoding=xudp#%E7%BE%8E%E5%9B%BD70",
    # 在此继续粘贴你提供的其他链接...
]

# ==========================================
# 2. 自动化核心类
# ==========================================
class AutoOptimizer:
    def __init__(self, config, links):
        self.config = config
        self.links = links
        # 核心修复：对 Token 进行 strip() 处理防止编码错误
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
        if len(self.status_log) > 15: self.status_log.pop(0)

    def parse_ips(self):
        ips = []
        for link in self.links:
            try:
                parts = urllib.parse.urlparse(link)
                # 提取 @ 后面的 IP 地址
                ip = parts.netloc.split('@')[-1].split(':')[0]
                ips.append(ip)
            except: continue
        return list(set(ips))

    def get_latency(self, ip):
        """测试 IP 延迟"""
        try:
            start = time.time()
            # 仅做连接测试，不下载内容以节省流量
            requests.get(f"https://{ip}", timeout=2, verify=False)
            return int((time.time() - start) * 1000)
        except:
            return 9999

    def update_cf_dns(self, ip):
        """同步 IP 到 Cloudflare"""
        base_url = "https://api.cloudflare.com/client/v4"
        try:
            # 1. 查找解析记录 ID
            list_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records?name={self.config['record_name']}"
            res = requests.get(list_url, headers=self.headers).json()
            
            if not res.get("success") or not res["result"]:
                self.log(f"❌ 未找到域名记录: {self.config['record_name']}")
                return False
            
            record = res["result"][0]
            if record["content"] == ip:
                self.log("✅ CF 记录已是最优，无需更新")
                return True

            # 2. 更新 A 记录
            update_url = f"{base_url}/zones/{self.config['zone_id']}/dns_records/{record['id']}"
            data = {
                "type": "A",
                "name": self.config['record_name'],
                "content": ip,
                "ttl": 60,
                "proxied": False
            }
            put_res = requests.put(update_url, headers=self.headers, json=data).json()
            return put_res.get("success")
        except Exception as e:
            self.log(f"❌ API 异常: {str(e)}")
            return False

    def run_loop(self):
        """后台持续运行的任务"""
        while True:
            self.log("🔄 开始自动优选巡检...")
            ips = self.parse_ips()
            results = []
            
            for ip in ips:
                delay = self.get_latency(ip)
                if delay < 9999:
                    results.append((ip, delay))
            
            if results:
                results.sort(key=lambda x: x[1])
                top_ip = results[0][0]
                self.log(f"🏆 测速完成！最优 IP: {top_ip} ({results[0][1]}ms)")
                
                if self.update_cf_dns(top_ip):
                    self.best_ip = top_ip
                    self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.log(f"🚀 自动同步成功")
            else:
                self.log("⚠️ 测速结果为空，请检查链接或网络")
            
            self.log("💤 进入休眠，10分钟后再次巡检...")
            time.sleep(600)

# ==========================================
# 3. Streamlit UI 
# ==========================================
def main():
    st.set_page_config(page_title="CF 节点自动优选", layout="centered")
    st.title("⚡ Cloudflare 自动部署系统")

    # 利用 session_state 确保后台线程只启动一次
    if 'optimizer' not in st.session_state:
        st.session_state.optimizer = AutoOptimizer(CF_CONFIG, VLESS_LINKS)
        t = threading.Thread(target=st.session_state.optimizer.run_loop, daemon=True)
        t.start()

    opt = st.session_state.optimizer

    # 数据展示区
    m1, m2 = st.columns(2)
    m1.metric("当前优选 IP", opt.best_ip)
    m2.metric("最后同步时间", opt.last_update.split(" ")[-1] if " " in opt.last_update else "尚未运行")

    st.subheader("📋 自动化运行日志")
    log_area = st.container(border=True)
    with log_area:
        for msg in reversed(opt.status_log):
            if "❌" in msg: st.error(msg)
            elif "🚀" in msg: st.success(msg)
            else: st.text(msg)

    # 自动刷新页面内容
    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()
