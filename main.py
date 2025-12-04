from flask import Flask, render_template, request, redirect, url_for, session , jsonify
import psycopg2
import hashlib
import os
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# --- DATABASE FORBINDELSE ---
def get_db():
    try:
        return psycopg2.connect(
            dbname=os.environ.get('DB_NAME', 'health'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'demens'),
            host=os.environ.get('DB_HOST', 'localhost'),
            port=os.environ.get('DB_PORT', '5432')
        )
    except psycopg2.Error as e:
        print(f"Database forbindelsesfejl: {e}")
        return None

# --- LOGIN KRAV DECORATOR ---
def login_required(func):
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__  # Flask kræver dette
    return wrapper

# --- ROUTES ---
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if not username or not password:
            return render_template("login.html", error="Indtast både brugernavn og password")

        conn = get_db()
        if not conn:
            return render_template("login.html", error="Database forbindelsesfejl")
        
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, username, password FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
            
            if user:
                # user[0] = id, user[1] = username, user[2] = password
                if password == user[2]:  # Direkte sammenligning da password er plain text
                    session["user"] = username
                    session["user_id"] = user[0]
                    return redirect(url_for("home"))
                else:
                    return render_template("login.html", error="Forkert password")
            else:
                return render_template("login.html", error="Bruger ikke fundet")
        except psycopg2.Error as e:
            return render_template("login.html", error="Database fejl")
        finally:
            conn.close()

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/home")
@login_required
def home():
    return render_template("home.html", user=session.get("user"))

@app.route("/bevæglese")
@login_required
def bevæglese():
    # Her kan du hente bevægelsesdata fra databasen og sende til template
    movement_data = []  # Erstat med faktisk datahentning
    return render_template("bevæglese.html", movement_data=movement_data)

@app.route("/bevægelse")
@login_required
def bevaegelse():
    # Hent bevægelsesdata fra din eksisterende bevaegelse tabel
    conn = get_db()
    movement_data = []
    
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT beveagelse, timestamp FROM bevaegelse ORDER BY timestamp DESC")
            rows = cur.fetchall()
            
            for row in rows:
                
                movement_text = "Bevægelse detekteret" if row[0] else "Ingen bevægelse"
                movement_data.append({
                    'type': movement_text,  
                    'date': row[1]          
                })
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
        finally:
            conn.close()
    
    return render_template("bevæglese.html", movement_data=movement_data)

@app.route("/temperatur_fugt")
@login_required  
def temperatur_fugt():
    
    conn = get_db()
    environment_data = []
    
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT timestamp, temperatur, fugtighed FROM temp_fugt ORDER BY timestamp DESC")
            rows = cur.fetchall()
            
            for row in rows:
                environment_data.append({
                    'date': row[0],
                    'temperature': row[1], 
                    'humidity': row[2],
                    'window_status': 'Auto' 
                })
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
        finally:
            conn.close()
            
    return render_template("tempertur_fugt.html", environment_data=environment_data)

@app.route("/door_control")
@login_required
def door_control():
    
    conn = get_db()
    door_status = "Ukendt"
    
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT is_the_door_open FROM door ORDER BY timestamp DESC LIMIT 1")
            result = cur.fetchone()
            if result:
                door_status = "Åben" if result[0] else "Lukket"
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
        finally:
            conn.close()
    
    return render_template("door_control.html", door_status=door_status)

@app.route("/api/temp_fugt", methods=["POST"])
def api_temp_fugt():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        temperatur = data.get("temperatur")
        fugtighed = data.get("fugtighed") 
        timestamp = data.get("timestamp")

        if temperatur is None or fugtighed is None or timestamp is None:
            return jsonify({"error": "Mangler felter"}), 400
        
        conn = get_db()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO temp_fugt (temperatur, fugtighed, timestamp) VALUES (%s, %s, %s)",
                (temperatur, fugtighed, timestamp)
            )
            conn.commit()
            print(f" Data modtaget: {temperatur}°C, {fugtighed}%, {timestamp}")
            return jsonify({"message": "Data gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500

@app.route("/api/pir", methods=["POST"])
def api_pir():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        pir_value = data.get("pir")
        timestamp = data.get("timestamp")

        if pir_value is None or timestamp is None:
            return jsonify({"error": "Mangler felter"}), 400
        
        conn = get_db()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            cur = conn.cursor()
            
            movement_bool = bool(pir_value)
            cur.execute(
                "INSERT INTO bevaegelse (beveagelse, timestamp) VALUES (%s, %s)",
                (movement_bool, timestamp)
            )
            conn.commit()
            movement_text = "Bevægelse detekteret" if movement_bool else "Ingen bevægelse"
            print(f"✅ PIR data modtaget: {movement_text} ({movement_bool}), {timestamp}")
            return jsonify({"message": "Bevægelse data gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500

# API endpoint for solenoid kontrol
@app.route("/api/solenoid", methods=["POST"])
def api_solenoid():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        action = data.get("action")  
        
        if action not in ["open", "close"]:
            return jsonify({"error": "Ugyldig handling. Brug 'open' eller 'close'"}), 400
        
        
        conn = get_db()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            cur = conn.cursor()
            
            is_open = True if action == "open" else False
            cur.execute(
                "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, NOW())",
                (is_open,)
            )
            conn.commit()
            print(f" Solenoid kommando: {action} -> {is_open}")
            return jsonify({"message": f"Dør kommando sendt: {action}"}), 200
        
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500


@app.route("/api/solenoid/check", methods=["GET"])
def api_solenoid_check():
    try:
        conn = get_db()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT is_the_door_open, timestamp, id
                FROM door 
                WHERE timestamp > NOW() - INTERVAL '10 seconds'
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            result = cur.fetchone()
            
            if result:
                command = "open" if result[0] else "close"
                
                # VIGTIG: Marker denne kommando som brugt ved at tilføje 1 time til timestamp
                cur.execute("""
                    UPDATE door 
                    SET timestamp = timestamp - INTERVAL '1 hour'
                    WHERE id = %s
                """, (result[2],))
                conn.commit()
                
                print(f"🔍 ESP32 henter kommando: {command} (ID: {result[2]})")
                return jsonify({"command": command}), 200
            
            return jsonify({"command": None}), 200
        
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500

# API endpoint for at logge døraktivitet
@app.route("/api/door_log", methods=["POST"])
def api_door_log():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        is_open = data.get("is_open") 
        timestamp = data.get("timestamp")

        if is_open is None or not timestamp:
            return jsonify({"error": "Mangler is_open eller timestamp"}), 400
        
        
        if isinstance(is_open, int):
            is_open = bool(is_open)
        
        conn = get_db()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, %s)",
                (is_open, timestamp)
            )
            conn.commit()
            status_text = "Åben" if is_open else "Lukket"
            print(f"🚪 Dør status logged: {status_text} ({is_open}), {timestamp}")
            return jsonify({"message": "Dør status gemt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


