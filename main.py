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
    # Hent bevægelsesdata fra database (som ESP32 sender)
    conn = get_db()
    movement_data = []
    
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT movement_type, date_recorded FROM movement_data ORDER BY date_recorded DESC")
            rows = cur.fetchall()
            
            for row in rows:
                movement_data.append({
                    'type': row[0],
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
    # Hent miljødata fra database (som ESP32 sender)
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
                    'window_status': 'Auto'  # Da din tabel ikke har vindue status
                })
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
        finally:
            conn.close()
            
    return render_template("tempertur_fugt.html", environment_data=environment_data)
#gemmer data fra vores esp32 til vores sql database som også bliver gemt via api´et 
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



# --- START APP ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


