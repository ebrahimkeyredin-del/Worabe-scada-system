import random
import sqlite3
import time
from datetime import datetime

print("==========================================")
print(" 🗄️ SCADA DATABASE ENGINE WITH CONTROL SYSTEM")
print("==========================================\n")

# 1. ከ Database ጋር መገናኘት
conn = sqlite3.connect("scada_memory.db")
cursor = conn.cursor()

# 2. ሰንጠረዦችን መፍጠር
cursor.execute("""
CREATE TABLE IF NOT EXISTS sensor_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    temperature REAL,
    voltage REAL,
    oil_pressure REAL,
    status TEXT
)
""")

# አዲሷ የቁጥጥር ሰንጠረዥ (Control Table)
cursor.execute("""
CREATE TABLE IF NOT EXISTS control_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    target_system TEXT,
    command_type TEXT,
    status TEXT
)
""")
conn.commit()

# =========================================================
# 🧹 3. AUTO-CLEANUP FUNCTION (ኢብራሂም የጨመረው ማጽጃ)
# =========================================================
def clean_old_sensor_data(connection, max_records=300):
    """
    በ sensor_data ቴብል ውስጥ ያለው የዳታ ብዛት ከ max_records (300) ሲበልጥ
    በጣም አሮጌ የሆኑትን (Oldest Records) በራስ-ሰር ያጸዳል።
    """
    db_cursor = connection.cursor()
    
    # የዳታውን አጠቃላይ ብዛት መቆጠር
    db_cursor.execute("SELECT COUNT(*) FROM sensor_data")
    total_count = db_cursor.fetchone()[0]
    
    # ብዛቱ ከ 300 በላይ ከሆነ ማጽዳት
    if total_count > max_records:
        records_to_delete = total_count - max_records
        db_cursor.execute(f"""
            DELETE FROM sensor_data 
            WHERE id IN (
                SELECT id FROM sensor_data 
                ORDER BY timestamp ASC 
                LIMIT {records_to_delete}
            )
        """)
        connection.commit()
        print(f"🧹 [AUTO-CLEANUP] {records_to_delete} አሮጌ ዳታዎች ከ 'sensor_data' ተወግደዋል።")

# =========================================================

print(
    "1️⃣ Database, 'sensor_data' እና 'control_commands' Table በተሳካ ሁኔታ"
    " ተዘጋጅተዋል!"
)
print("2️⃣ Engineው መቆጣጠሪያዎችን እና ሴንሰሮችን ማስተናገድ ጀምሯል...\n")

# የማሽኑ/የኤሌክትሪክ መስመሩ አሁናዊ ሁኔታ (State)
system_power = "ON"

try:
  while True:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # A. መጀመሪያ ከ Dashboard የመጣ PENDING ትእዛዝ ካለ መፈተሽ
    cursor.execute(
        "SELECT id, command_type FROM control_commands WHERE status ="
        " 'PENDING' ORDER BY id ASC LIMIT 1"
    )
    pending_command = cursor.fetchone()

    if pending_command:
      cmd_id, cmd_type = pending_command
      if cmd_type == "STOP":
        system_power = "OFF"
        print(f"🛑 [CONTROL COMMAND] Emergency STOP Executed at {timestamp}!")
      elif cmd_type == "START":
        system_power = "ON"
        print(f"🟢 [CONTROL COMMAND] System RESTARTED at {timestamp}!")

      # የትእዛዙን Status ወደ EXECUTED መቀየር
      cursor.execute(
          "UPDATE control_commands SET status = 'EXECUTED' WHERE id = ?",
          (cmd_id,),
      )
      conn.commit()

    # B. የሲስተሙ ሁኔታ (Power ON/OFF) መነሳትና መውደቅ
    if system_power == "ON":
      temperature = random.randint(60, 110)
      voltage = random.uniform(215.0, 250.0)  # ከፍተኛ ቮልቴጅ እንዲፈጠር
      oil_pressure = random.uniform(1.0, 5.0)

      # 1. ⚡ የከፍተኛ ቮልቴጅ AUTO-TRIP LOGIC (ኤብራሂም የጨመረው)
      if voltage >= 270.0:
        system_power = "OFF"
        temperature = 25.0
        voltage = 0.0
        oil_pressure = 0.0
        status = "VOLTAGE_TRIPPED"
        print(
            f"⚡ [AUTO PROTECTION] High Voltage Detected! System TRIPPED to"
            f" OFF at {timestamp}"
        )

      # 2. የአላርም ሁኔታዎችን መፈተሽ
      elif temperature >= 85 or oil_pressure <= 2.0:
        status = "CRITICAL_ALERT"
      else:
        status = "NORMAL"

    else:
      # ሲስተሙ በ Control ወይም በ Auto-Trip ከተጠፋ
      temperature = 25.0
      voltage = 0.0
      oil_pressure = 0.0
      status = "POWER_OFF"

    # C. ወደ sensor_data መጻፍ
    cursor.execute(
        """
        INSERT INTO sensor_data (timestamp, temperature, voltage, oil_pressure, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (timestamp, temperature, voltage, oil_pressure, status),
    )
    conn.commit()

    # D. 🧹 AUTO-CLEANUP LOGIC እዚህ ጋር ይጠራል
    clean_old_sensor_data(conn, max_records=300)

    print(
        f" 💾 [{timestamp}] Power: {system_power} | Temp: {temperature}°C |"
        f" Volt: {voltage:.1f}V | Status: {status}"
    )

    time.sleep(1)

except KeyboardInterrupt:
  conn.close()
  print("\n🔒 የ Database ስራው ተቋርጧል።")

 


