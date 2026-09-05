import json
import os
import time
import bcrypt
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from sklearn.ensemble import RandomForestClassifier
from sqlalchemy import create_engine, text

# ----------------- PAGE CONFIG -----------------
st.set_page_config(
    page_title="Worabe SCADA Live Dashboard", layout="wide", page_icon="⚡"
)

# ----------------- SUPABASE POSTGRESQL CONNECTION -----------------
DATABASE_URL = "postgresql://postgres:Worabe#Scada2026!System@db.iagzsbwlrxosibrpzaue.supabase.co:5432/postgres"

@st.cache_resource
def get_db_engine():
    """PostgreSQL Engine የሚፈጥር ተግባር"""
    return create_engine(DATABASE_URL, pool_pre_ping=True)

db_engine = get_db_engine()

# ----------------- TELEGRAM BOT CONFIGURATION -----------------
TELEGRAM_BOT_TOKEN = "8485027430:AAFCTxiHL9bQLuEP66F5V-qUgQLbq93mLLE"
TELEGRAM_CHAT_ID = "6981855026"

def send_telegram_alert(message):
    """ለቴሌግራም አደጋ መልእክት መላኪያ ተግባር"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

# ----------------- PDF REPORT GENERATOR FUNCTION -----------------
def generate_pdf_report(pdf_filename="worabe_scada_report.pdf"):
    try:
        query = text("SELECT timestamp, temperature, voltage, status FROM sensor_data ORDER BY id DESC LIMIT 50")
        with db_engine.connect() as conn:
            df_rows = pd.read_sql_query(query, conn)
        rows = df_rows.values.tolist()[::-1]
    except Exception:
        rows = []

    if not rows:
        return None

    timestamps = [str(r[0]).split(" ")[1] if " " in str(r[0]) else str(r[0]) for r in rows]
    temperatures = [float(r[1]) for r in rows]
    voltages = [float(r[2]) for r in rows]

    plt.figure(figsize=(6, 2.5))
    plt.plot(timestamps, temperatures, label="Temp (°C)", color="red")
    plt.plot(timestamps, voltages, label="Volt (V)", color="blue")
    plt.xticks(rotation=45, fontsize=6)
    plt.legend()
    plt.tight_layout()
    graph_path = "temp_chart.png"
    plt.savefig(graph_path, dpi=150)
    plt.close()

    doc = SimpleDocTemplate(pdf_filename, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    title = Paragraph("<b>WORABE SCADA SYSTEM - AUTOMATED REPORT</b>", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    max_temp = max(temperatures) if temperatures else 0
    avg_volt = (sum(voltages) / len(voltages)) if voltages else 0
    summary_text = Paragraph(f"<b>Report Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>"
                             f"<b>Max Temperature:</b> {max_temp:.1f}°C | <b>Avg Voltage:</b> {avg_volt:.1f}V", styles['Normal'])
    elements.append(summary_text)
    elements.append(Spacer(1, 12))

    if os.path.exists(graph_path):
        elements.append(Image(graph_path, width=450, height=180))
        elements.append(Spacer(1, 12))

    table_data = [["Time", "Temp (°C)", "Voltage (V)", "Status"]]
    for r in rows[-5:]:
        t_str = str(r[0]).split(" ")[1] if " " in str(r[0]) else str(r[0])
        table_data.append([t_str, str(r[1]), f"{float(r[2]):.1f}", str(r[3])])

    t = Table(table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.navy),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(t)

    doc.build(elements)

    if os.path.exists(graph_path):
        os.remove(graph_path)

    return pdf_filename

# ----------------- 1. DATABASE SETUP -----------------
def init_db():
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role VARCHAR(50) NOT NULL,
                failed_attempts INT DEFAULT 0,
                is_locked BOOLEAN DEFAULT FALSE
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS control_commands (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(100) NOT NULL,
                target_system VARCHAR(100) NOT NULL,
                command_type VARCHAR(100) NOT NULL,
                status VARCHAR(50) NOT NULL
            )
        """))

        res_admin = conn.execute(text("SELECT id FROM users WHERE username = 'admin'")).fetchone()
        if not res_admin:
            hashed_admin = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            conn.execute(
                text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                {"u": "admin", "p": hashed_admin, "r": "Admin"}
            )

        res_oper = conn.execute(text("SELECT id FROM users WHERE username = 'operator'")).fetchone()
        if not res_oper:
            hashed_oper = bcrypt.hashpw("oper123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            conn.execute(
                text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                {"u": "operator", "p": hashed_oper, "r": "Operator"}
            )

init_db()

# ----------------- 2. SESSION STATE MANAGEMENT -----------------
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""

if "last_telegram_sent" not in st.session_state:
    st.session_state["last_telegram_sent"] = 0

# ----------------- DATA FETCH HELPER -----------------
def get_scada_data(alerts_only=False):
    try:
        if alerts_only:
            query = text("SELECT timestamp, temperature, voltage, oil_pressure, status FROM sensor_data WHERE status = 'CRITICAL_ALERT' ORDER BY id DESC LIMIT 100")
        else:
            query = text("SELECT timestamp, temperature, voltage, oil_pressure, status FROM sensor_data ORDER BY id DESC LIMIT 100")
        
        with db_engine.connect() as conn:
            df = pd.read_sql_query(query, conn)
    except Exception:
        df = pd.DataFrame(columns=["timestamp", "temperature", "voltage", "oil_pressure", "status"])
    return df

# ----------------- MACHINE LEARNING TRAINER -----------------
def train_predictive_model():
    """ለአደጋ ግምት የሚያገለግል ቀላል Random Forest ML Model ያዘጋጃል"""
    np.random.seed(42)
    temp_data = np.random.uniform(20, 90, 500)
    volt_data = np.random.uniform(180, 260, 500)
    oil_data = np.random.uniform(1.0, 5.0, 500)

    labels = []
    for t, v, o in zip(temp_data, volt_data, oil_data):
        if t > 70 or v < 190 or v > 250 or o < 2.0:
            labels.append(1)
        else:
            labels.append(0)

    X = np.column_stack((temp_data, volt_data, oil_data))
    y = np.array(labels)

    model = RandomForestClassifier(n_estimators=50, random_state=42)
    model.fit(X, y)
    return model

ml_model = train_predictive_model()

# ----------------- 3. LOGIN PAGE -----------------
if not st.session_state["logged_in"]:
    st.title("🔐 SCADA System Login")

    col_login, _ = st.columns([1, 1])
    with col_login:
        username_input = st.text_input("Username")
        password_input = st.text_input("Password", type="password")
        login_btn = st.button("Login")

    if login_btn:
        with db_engine.begin() as conn:
            user = conn.execute(
                text("SELECT id, password, role, failed_attempts, is_locked FROM users WHERE username = :u"),
                {"u": username_input}
            ).fetchone()

            if user:
                user_id, stored_hashed_password, role, failed_attempts, is_locked = user

                if is_locked:
                    st.error("🔒 አካውንትዎ ተቆልፏል! እባክዎን ዋናውን SCADA Admin/Engineer ያነጋግሩ።")
                elif bcrypt.checkpw(password_input.encode("utf-8"), stored_hashed_password.encode("utf-8")):
                    conn.execute(
                        text("UPDATE users SET failed_attempts = 0 WHERE id = :id"),
                        {"id": user_id}
                    )
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = username_input
                    st.session_state["role"] = role
                    st.success("በተሳካ ሁኔታ ገብተዋል!")
                    st.rerun()
                else:
                    new_attempts = failed_attempts + 1
                    if new_attempts >= 5:
                        conn.execute(
                            text("UPDATE users SET failed_attempts = :fa, is_locked = TRUE WHERE id = :id"),
                            {"fa": new_attempts, "id": user_id}
                        )
                        st.error("❌ 5 ጊዜ ተሳስተዋል። አካውንትዎ ተቆልፏል!")
                    else:
                        conn.execute(
                            text("UPDATE users SET failed_attempts = :fa WHERE id = :id"),
                            {"fa": new_attempts, "id": user_id}
                        )
                        st.error(f"❌ የይለፍ ቃል ተሳስቷል! የከሸፈ ሙከራ፦ {new_attempts}/5")
            else:
                st.error("❌ እንደዚህ ያለ ተጠቃሚ አልተገኘም!")

# ----------------- 4. MAIN DASHBOARD PAGE (LOGGED IN) -----------------
else:
    st.sidebar.markdown(f"### 👤 **{st.session_state['username']}**")
    st.sidebar.write(f"**Role:** {st.session_state['role']}")

    if st.sidebar.button("🚪 Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = ""
        st.session_state["role"] = ""
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.header("🧭 Navigation")
    page_choice = st.sidebar.selectbox(
        "ምረጡ (Select View):",
        [
            "🛰️ GIS Satellite Map View",
            "📈 Real-Time Dashboard & Charts",
            "🧠 Predictive Analytics & AI Forecasting",
            "👥 Manage Users & System Control"
        ]
    )

    with st.sidebar.expander("🔑 Change Password"):
        current_pass = st.text_input("Current Password", type="password", key="chg_curr_pass")
        new_pass = st.text_input("New Password", type="password", key="chg_new_pass")
        confirm_pass = st.text_input("Confirm New Password", type="password", key="chg_conf_pass")

        if st.button("Update Password"):
            if not current_pass or not new_pass or not confirm_pass:
                st.sidebar.error("❌ እባክዎን ሁሉንም ቦታዎች ይሙሉ!")
            else:
                active_user = st.session_state["username"]
                with db_engine.begin() as conn:
                    db_hashed_pass = conn.execute(
                        text("SELECT password FROM users WHERE username = :u"),
                        {"u": active_user}
                    ).scalar()

                    if not bcrypt.checkpw(current_pass.encode("utf-8"), db_hashed_pass.encode("utf-8")):
                        st.sidebar.error("❌ ያሁኑ የይለፍ ቃልዎ ተሳስቷል!")
                    elif new_pass != confirm_pass:
                        st.sidebar.error("❌ አዲሱ የይለፍ ቃል እና ድጋሚ የጻፉት አልተመሳሰሉም!")
                    else:
                        new_hashed_pass = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                        conn.execute(
                            text("UPDATE users SET password = :p WHERE username = :u"),
                            {"p": new_hashed_pass, "u": active_user}
                        )
                        st.sidebar.success("✅ የይለፍ ቃልዎ በጥንቃቄ ተቀይሯል!")

    st.sidebar.markdown("---")

    st.sidebar.header("📄 PDF Report Generator")
    if st.sidebar.button("📥 Generate PDF Report"):
        with st.spinner("PDF ሪፖርቱ ከነግራፉ በመዘጋጀት ላይ ነው..."):
            generated_pdf = generate_pdf_report()
            if generated_pdf and os.path.exists(generated_pdf):
                with open(generated_pdf, "rb") as pdf_file:
                    st.sidebar.download_button(
                        label="⬇️ Download PDF Report",
                        data=pdf_file,
                        file_name="Worabe_SCADA_Report.pdf",
                        mime="application/pdf"
                    )
                st.sidebar.success("✅ ሪፖርቱ ተዘጋጅቷል! ማውረድ ይችላሉ።")
            else:
                st.sidebar.error("❌ ዳታ ባለመኖሩ PDF ማዘጋጀት አልተቻለም!")

    worabe_substations = [
        {"name": "Werabe Main Power Substation", "lat": 7.884072, "lon": 38.210936},
        {"name": "Werabe Industrial Area Substation", "lat": 7.881055, "lon": 38.189608},
        {"name": "Werabe Comprehensive Hospital Line", "lat": 7.838394, "lon": 38.185102},
        {"name": "Werabe Fedlu Flour Factory Line", "lat": 7.828897, "lon": 38.173957},
        {"name": "Werabe Poly-Technic College Line", "lat": 7.826438, "lon": 38.170329},
        {"name": "Werabe University Substation", "lat": 7.823080, "lon": 38.189384},
    ]

    # ----------------- PAGE 1: 🛰️ GIS SATELLITE MAP VIEW -----------------
    if page_choice == "🛰️ GIS Satellite Map View":
        st.title("🛰️ Worabe City Electrical Grid - GIS Satellite Map")
        st.info("💡 Ultra-Smooth Real-Time Map: Zoom and Pan freely! Map stays completely stable while system telemetry updates below.")

        df_curr = get_scada_data()
        latest_status = "NORMAL"
        latest_volt = 220.0
        latest_temp = 45.0
        latest_oil = 3.5

        if not df_curr.empty:
            latest = df_curr.iloc[0]
            latest_status = str(latest["status"])
            latest_volt = float(latest["voltage"])
            latest_temp = float(latest["temperature"])
            latest_oil = float(latest["oil_pressure"])

        is_critical = (latest_status == "CRITICAL_ALERT")
        marker_color = "#FF0000" if is_critical else "#00FF00"

        subs_json = json.dumps(worabe_substations)

        custom_map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <style>
                #map {{ width: 100%; height: 500px; border-radius: 10px; }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([7.8500, 38.1850], 13);
                L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
                    attribution: 'Esri World Imagery'
                }}).addTo(map);

                var subs = {subs_json};
                subs.forEach(function(sub) {{
                    var circle = L.circleMarker([sub.lat, sub.lon], {{
                        color: '{marker_color}',
                        fillColor: '{marker_color}',
                        fillOpacity: 0.8,
                        radius: 10
                    }}).addTo(map);

                    circle.bindPopup("<b>" + sub.name + "</b><br>Status: {latest_status}<br>Voltage: {latest_volt:.1f}V");
                }});
            </script>
        </body>
        </html>
        """

        components.html(custom_map_html, height=520, scrolling=False)

        st.markdown("---")
        st.subheader("📊 Live Substation Telemetry")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall System Status", latest_status)
        c2.metric("Voltage (V)", f"{latest_volt:.1f}")
        c3.metric("Temperature (°C)", f"{latest_temp:.1f}")
        c4.metric("Oil Pressure (bar)", f"{latest_oil:.1f}")

        st.dataframe(df_curr.head(10), use_container_width=True)

    # ----------------- PAGE 2: 📈 REAL-TIME DASHBOARD & CHARTS -----------------
    elif page_choice == "📈 Real-Time Dashboard & Charts":
        st.title("⚡ Electrical SCADA Real-Time Control & Monitoring System")

        show_alerts_only = st.sidebar.checkbox("🚨 Show Critical Alerts Only")

        @st.fragment(run_every=2)
        def render_realtime_data():
            df_data = get_scada_data(show_alerts_only)
            df_data = df_data.fillna(0)

            if not df_data.empty:
                latest = df_data.iloc[0]

                if latest["status"] == "CRITICAL_ALERT":
                    current_time = time.time()
                    if (current_time - st.session_state["last_telegram_sent"]) >= 30:
                        alert_msg = (
                            "🚨 Worabe SCADA Critical Alert!\n"
                            f"⏰ Time: {latest['timestamp']}\n"
                            f"🌡️ Temp: {latest['temperature']:.1f} °C\n"
                            f"⚡ Voltage: {latest['voltage']:.1f} V\n"
                            f"🛢️ Oil Pressure: {latest['oil_pressure']:.1f} bar\n"
                            "⚠️ Immediate Inspection Required!"
                        )
                        send_telegram_alert(alert_msg)
                        st.session_state["last_telegram_sent"] = current_time

                col1, col2, col3 = st.columns(3)
                col1.metric("Temperature (°C)", f"{latest['temperature']:.1f}")
                col2.metric("Voltage (V)", f"{latest['voltage']:.1f}")
                col3.metric("Oil Pressure (bar)", f"{latest['oil_pressure']:.1f}")

                st.subheader("📈 Live Sensor Real-Time Trend Charts")
                chart_data = df_data.iloc[::-1].copy()
                chart_data.set_index("timestamp", inplace=True)

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.caption("🌡️ Temperature")
                    st.line_chart(chart_data["temperature"])
                with c2:
                    st.caption("⚡ Voltage")
                    st.line_chart(chart_data["voltage"])
                with c3:
                    st.caption("🛢️ Oil Pressure")
                    st.line_chart(chart_data["oil_pressure"])

                st.subheader("📊 Live Sensor Log Table")
                if show_alerts_only:
                    st.warning("🚨 Displaying Critical Alert Events Only!")
                st.dataframe(df_data, use_container_width=True)

        render_realtime_data()

    # ----------------- PAGE 3: 🧠 PREDICTIVE ANALYTICS & AI FORECASTING -----------------
    elif page_choice == "🧠 Predictive Analytics & AI Forecasting":
        st.title("🧠 SCADA AI Predictive Analytics & Transformer Health Index")
        st.markdown("ይህ ገፅ በ **Machine Learning (Random Forest Classifier)** በመጠቀም ትራንስፎርመሮች ከጥቅም ውጭ ከመሆናቸው ወይም ብልሽት ከማጋጠሙ በፊት በቅድሚያ የአደጋ ስጋት ደረጃቸውን ይተነብያል።")

        df_ml = get_scada_data()

        if df_ml.empty or len(df_ml) < 5:
            st.warning("⚠️ ለትንተና የሚሆን በቂ የሴንሰር መረጃ አልተገኘም። እባክዎን የሲስተም ሴንሰሮችን ያበሩ!")
        else:
            latest = df_ml.iloc[0]
            curr_temp = float(latest["temperature"])
            curr_volt = float(latest["voltage"])
            curr_oil = float(latest["oil_pressure"])

            input_features = np.array([[curr_temp, curr_volt, curr_oil]])
            failure_prob = ml_model.predict_proba(input_features)[0][1] * 100
            health_index = max(0, 100 - (failure_prob * 0.9))

            st.markdown("---")
            col_a, col_b, col_c = st.columns(3)

            with col_a:
                st.metric("🏥 Transformer Health Index", f"{health_index:.1f}%")
                if health_index > 75:
                    st.success("💚 የትራንስፎርመሩ ጤንነት በጣም በጥሩ ደረጃ ላይ ይገኛል።")
                elif health_index > 50:
                    st.warning("💛 ጥንቃቄ ያስፈልጋል፤ የጤንነት መጠኑ እየቀነሰ ነው።")
                else:
                    st.error("🔴 ትኩረት ይሻል! ትራንስፎርመሩ አደጋ ላይ ነው! ")

            with col_b:
                st.metric("🚨 Predicted Failure Probability", f"{failure_prob:.1f}%")
                if failure_prob < 30:
                    st.success("🟢 LOW RISK: የአደጋ ስጋት የለም።")
                elif failure_prob < 70:
                    st.warning("🟠 MEDIUM RISK: ክትትል ሊደረግበት ይገባል።")
                else:
                    st.error("🚨 HIGH CRITICAL RISK: የብልሽት አደጋ ሊፈጠር ይችላል!")

            with col_c:
                st.metric("🤖 Active ML Engine", "Random Forest Classifier")
                st.info("💡 ሞዴሉ የሙቀት፣ ቮልቴጅ እና የዘይት ጫናን አብሮ በመተንተን የተዘጋጀ ነው።")

            st.markdown("---")
            st.subheader("🔮 Interactive Trend Forecasting (Next Hours)")

            times = pd.date_range(end=datetime.now(), periods=20, freq='5min')
            future_times = pd.date_range(start=datetime.now(), periods=10, freq='5min')

            hist_temps = df_ml['temperature'].head(20).values[::-1]
            if len(hist_temps) < 20:
                hist_temps = np.pad(hist_temps, (20 - len(hist_temps), 0), 'edge')

            future_temps = [hist_temps[-1] + (i * 0.8 if failure_prob > 50 else i * -0.2) for i in range(1, 11)]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=times, y=hist_temps, mode='lines+markers', name='Historical Temp (°C)', line=dict(color='blue', width=2)))
            fig.add_trace(go.Scatter(x=future_times, y=future_temps, mode='lines+markers', name='Predicted Temp Trend (°C)', line=dict(color='firebrick', width=3, dash='dash')))

            fig.update_layout(
                title="🌡️ Temperature History vs Projected Trend Forecast",
                xaxis_title="Time",
                yaxis_title="Temperature (°C)",
                hovermode="x unified",
                template="plotly_dark"
            )

            st.plotly_chart(fig, use_container_width=True)

    # ----------------- PAGE 4: 👥 MANAGE USERS & SYSTEM CONTROL -----------------
    elif page_choice == "👥 Manage Users & System Control":
        st.title("⚙️ System Management & User Administration")

        st.subheader("🕹️ System Control Panel")
        if st.session_state["role"] == "Admin":
            col_ctl1, col_ctl2 = st.columns(2)
            with col_ctl1:
                if st.button("🛑 EMERGENCY STOP", type="primary"):
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    with db_engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO control_commands (timestamp, target_system, command_type, status) VALUES (:t, 'MAIN_GRID', 'STOP', 'PENDING')"),
                            {"t": timestamp}
                        )
                    st.error("🚨 STOP command sent to Engine!")

            with col_ctl2:
                if st.button("🟢 START SYSTEM"):
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    with db_engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO control_commands (timestamp, target_system, command_type, status) VALUES (:t, 'MAIN_GRID', 'START', 'PENDING')"),
                            {"t": timestamp}
                        )
                    st.success("✅ START command sent to Engine!")
        else:
            st.info("ℹ️ እርስዎ Operator ስለሆኑ ዳታ ማየት ብቻ ይችላሉ። የመቆጣጠር ስልጣን የለዎትም። (Control Panel ለመጠቀም በ Admin አካውንት ይግቡ)")

        st.markdown("---")

        if st.session_state["role"] == "Admin":
            st.subheader("👥 Manage Users & Unlock Accounts")
            col_manage, col_add = st.columns([1, 1])

            with col_manage:
                st.subheader("📋 Registered Users")
                with db_engine.connect() as conn:
                    users_df = pd.read_sql_query(text("SELECT id, username, role, failed_attempts, is_locked FROM users"), conn)
                st.dataframe(users_df, use_container_width=True)

                locked_users = users_df[users_df["is_locked"] == True]["username"].tolist()
                if locked_users:
                    user_to_unlock = st.selectbox("የተቆለፈ አካውንት ይምረጡ", locked_users)
                    if st.button("🔓 Unlock Account"):
                        with db_engine.begin() as conn:
                            conn.execute(
                                text("UPDATE users SET failed_attempts = 0, is_locked = FALSE WHERE username = :u"),
                                {"u": user_to_unlock}
                            )
                        st.success(f"አካውንት {user_to_unlock} ተከፍቷል!")
                        st.rerun()
                else:
                    st.info("ምንም የተቆለፈ አካውንት የለም።")

            with col_add:
                st.subheader("➕ Add New User")
                new_username = st.text_input("New Username", key="new_user")
                new_password = st.text_input("New Password", type="password", key="new_pass")
                new_role = st.selectbox("Role", ["Operator", "Admin"], key="new_role")

                if st.button("Register User"):
                    if not new_username or not new_password:
                        st.error("❌ እባክዎን ሁሉንም ቦታዎች በትክክል ይሙሉ!")
                    else:
                        with db_engine.begin() as conn:
                            exists = conn.execute(
                                text("SELECT username FROM users WHERE username = :u"),
                                {"u": new_username}
                            ).fetchone()

                            if exists:
                                st.error(f"❌ '{new_username}' የሚባል ተጠቃሚ አስቀድሞ ተመዝግቧል!")
                            else:
                                hashed_new_pass = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                                conn.execute(
                                    text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                                    {"u": new_username, "p": hashed_new_pass, "r": new_role}
                                )
                                st.success(f"✅ ተጠቃሚ {new_username} ({new_role}) በትክክል ተመዝግቧል!")
                                st.rerun()

        st.markdown("---")
        st.subheader("📥 Export CSV Reports")
        col_exp1, col_exp2 = st.columns(2)

        with col_exp1:
            try:
                with db_engine.connect() as conn:
                    full_df = pd.read_sql_query(text("SELECT * FROM sensor_data ORDER BY id DESC"), conn)
            except Exception:
                full_df = pd.DataFrame()
            st.download_button(
                label="📄 Download Full History (CSV)",
                data=full_df.to_csv(index=False).encode("utf-8"),
                file_name="SCADA_Full_Report.csv",
                key="btn_full",
            )

        with col_exp2:
            try:
                with db_engine.connect() as conn:
                    alert_df = pd.read_sql_query(text("SELECT * FROM sensor_data WHERE status = 'CRITICAL_ALERT' ORDER BY id DESC"), conn)
            except Exception:
                alert_df = pd.DataFrame()
            st.download_button(
                label="🚨 Download Critical Alerts Only (CSV)",
                data=alert_df.to_csv(index=False).encode("utf-8"),
                file_name="SCADA_Critical_Alerts.csv",
                key="btn_alert",
            )
