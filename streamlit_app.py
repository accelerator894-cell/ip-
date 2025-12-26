import streamlit as st
import socket
import requests
import time

# 网页基础配置
st.set_page_config(page_title="节点全能诊断", page_icon="🚀", layout="centered")

st.title("🛡️ 节点质量全方位诊断工具")
st.markdown("---")

# 用户输入区
target = st.text_input("请输入探测域名", "speed.milet.qzz.io")

if st.button("开始全面诊断"):
    with st.spinner('🔍 正在拉取全球大数据并探测延迟...'):
        try:
            # 1. 延迟测试
            start = time.time()
            ip = socket.gethostbyname(target)
            latency = (time.time() - start) * 1000
            
            # 显示核心指标
            col1, col2 = st.columns(2)
            col1.metric("解析 IP", ip)
            col2.metric("响应延迟", f"{latency:.2f} ms")

            # 2. 地理位置与风险检测 (中文)
            url = f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,country,regionName,city,isp,proxy,hosting"
            res = requests.get(url, timeout=5).json()

            if res['status'] == 'success':
                st.write(f"🌍 **物理归属**: {res['country']} · {res['regionName']} · {res['city']}")
                st.write(f"🏢 **运营商**: {res['isp']}")
                
                # 3. 风险评估逻辑
                st.subheader("🛡️ 风险评估")
                h, p = res.get('hosting', False), res.get('proxy', False)
                
                if not h and not p:
                    st.success("纯净等级: ⭐⭐⭐⭐⭐ (顶级住宅级)")
                    st.toast("节点非常纯净，适合养号！")
                else:
                    st.warning("纯净等级: ⭐⭐ (机房/IDC 广播段)")
                    st.info("提示：检测到机房特征，风控分可能略高。")
                    
        except Exception as e:
            st.error(f"❌ 探测失败: {e}")

st.markdown("---")
st.caption("由 Streamlit & Cloudflare 优选技术驱动")
