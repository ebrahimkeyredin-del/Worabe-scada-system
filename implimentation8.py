import os
import random
import time
from datetime import datetime
import psycopg2

# 1. Supabase PostgreSQL Connection String
DATABASE_URL = "postgresql://postgres:Worabe#Scada2026!System@db.iagzsbwlrxosibrpzaue.supabase.co:5432/postgres"


def init_db():
    """የ Supabase/PostgreSQL ዳታቤዝ ቴብሎችን መፍጠሪያ"""
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # A. የሴንሰር ዳታ ማከማቻ ቴብል
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_data (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            temperature REAL NOT NULL,
            voltage REAL NOT NULL,
            oil_pressure REAL NOT NULL,
            status VARCHAR(50) NOT NULL
        );
    """
    )

    # B. የቁጥጥር ትእዛዞች ማከማቻ ቴብል
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS control_commands (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            target_system VARCHAR(100),
            command_type VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL
        );
    """
    )

    conn.commit()
    cursor.close()
    conn.close()
    print(
        "1️⃣ Supabase Database, 'sensor_data' እና 'control_commands' Tables"
        " ተዘጋጅተዋል!"
    )


def clean_old_sensor_data(connection, max_records=300):
    """በ sensor_data ቴብል ውስጥ ያለው የዳታ ብዛት ከ 300 ሲበልጥ አሮጌዎችን በራስ-ሰር ያጸዳል"""
    db_cursor = connection.cursor()
    db_cursor.execute("SELECT COUNT(*) FROM sensor_data")
    total_count = db_cursor.fetchone()[0]

    if total_count > max_records:
        records_to_delete = total_count - max_records
        db_cursor.execute(
            """
            DELETE FROM sensor_data 
            WHERE id IN (
                SELECT id FROM sensor_data 
                ORDER BY timestamp ASC 
                LIMIT %s
            )
        """,
            (records_to_delete,),
        )
        connection.commit()
        print(
            f"🧹 [AUTO-CLEANUP] {records_to_delete} አሮጌ ዳታዎች ከ 'sensor_data'"
            " ተወግደዋል።"
        )
    db_cursor.close()


def run_scada_engine():
    """የ SCADA Engine እና Control Loop"""
    system_power = "ON"
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    print("2️⃣ Engineው መቆጣጠሪያዎችን እና ሴንሰሮችን ማስተናገድ ጀምሯል...\n")

    try:
        while True:
            now = datetime.now()

            # A. ከ Dashboard የመጣ PENDING ትእዛዝ ካለ መፈተሽ
            cursor.execute(
                "SELECT id, command_type FROM control_commands WHERE status ="
                " 'PENDING' ORDER BY id ASC LIMIT 1;"
            )
            pending_command = cursor.fetchone()

            if pending_command:
                cmd_id, cmd_type = pending_command
                if cmd_type == "STOP":
                    system_power = "OFF"
                    print(
                        f"🛑 [CONTROL COMMAND] Emergency STOP Executed at"
                        f" {now.strftime('%H:%M:%S')}!"
                    )
                elif cmd_type == "START":
                    system_power = "ON"
                    print(
                        f"🟢 [CONTROL COMMAND] System RESTARTED at"
                        f" {now.strftime('%H:%M:%S')}!"
                    )

                # የትእዛዙን Status ወደ EXECUTED መቀየር
                cursor.execute(
                    "UPDATE control_commands SET status = 'EXECUTED' WHERE id"
                    " = %s;",
                    (cmd_id,),
                )
                conn.commit()

            # B. የሲስተሙ ሁኔታ (Power ON/OFF) መነሳትና መውደቅ
            if system_power == "ON":
                temperature = random.randint(60, 110)
                voltage = random.uniform(215.0, 280.0)
                oil_pressure = round(random.uniform(1.0, 5.0), 2)

                # 1. ⚡ የከፍተኛ ቮልቴጅ AUTO-TRIP LOGIC
                if voltage >= 270.0:
                    system_power = "OFF"
                    temperature = 25.0
                    voltage = 0.0
                    oil_pressure = 0.0
                    status = "VOLTAGE_TRIPPED"
                    print(
                        f"⚡ [AUTO PROTECTION] High Voltage Detected! System"
                        f" TRIPPED to OFF at {now.strftime('%H:%M:%S')}"
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

            # C. ወደ Supabase sensor_data መጻፍ
            cursor.execute(
                """
                INSERT INTO sensor_data (timestamp, temperature, voltage, oil_pressure, status)
                VALUES (%s, %s, %s, %s, %s);
            """,
                (now, temperature, voltage, oil_pressure, status),
            )
            conn.commit()

            # D. 🧹 AUTO-CLEANUP LOGIC
            clean_old_sensor_data(conn, max_records=300)

            print(
                f" 💾 [{now.strftime('%H:%M:%S')}] Power: {system_power} | Temp:"
                f" {temperature}°C | Volt: {voltage:.1f}V | Press:"
                f" {oil_pressure} bar | Status: {status}"
            )

            time.sleep(2)

    except KeyboardInterrupt:
        cursor.close()
        conn.close()
        print("\n🔒 የ Database ስራው ተቋርጧል።")


if __name__ == "__main__":
    init_db()
    run_scada_engine()
