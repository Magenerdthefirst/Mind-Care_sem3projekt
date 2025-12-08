import os
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps

import psycopg2
import psycopg2.extensions
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

# Flask application configuration
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour session timeout

# --- CONSTANTS ---
MAX_TEMPERATURE = 100.0
MIN_TEMPERATURE = -50.0
MAX_HUMIDITY = 100.0
MIN_HUMIDITY = 0.0
MAX_INPUT_LENGTH = 100
COMMAND_TIMEOUT_SECONDS = 10
SESSION_TIMEOUT_HOURS = 1

# ESP32 Window Control Thresholds (same as ESP32 code)
WINDOW_TEMP_THRESHOLD = 25.0
WINDOW_HUMIDITY_THRESHOLD = 70.0


class DatabaseConfig:
    """Database konfigurationsklasse for centraliseret konfigurationsstyring.
    
    Denne klasse indkapsler alle databasekonfigurationsparametre og giver
    et enkelt punkt for konfigurationsstyring med understøttelse af miljøvariabler.
    """
    
    def __init__(self) -> None:
        """Initialiser databasekonfiguration fra miljøvariabler."""
        self.dbname: str = os.environ.get('DB_NAME', 'health')
        self.user: str = os.environ.get('DB_USER', 'postgres')
        self.password: str = os.environ.get('DB_PASSWORD', 'demens')
        self.host: str = os.environ.get('DB_HOST', 'localhost')
        self.port: str = os.environ.get('DB_PORT', '5432')
        self.connect_timeout: int = int(os.environ.get('DB_TIMEOUT', '10'))

    def get_connection_params(self) -> Dict[str, Any]:
        """Hent databaseforbindelsesparametre som ordbog.
        
        Returns:
            Dict containing database connection parameters
        """
        return {
            'dbname': self.dbname,
            'user': self.user,
            'password': self.password,
            'host': self.host,
            'port': self.port,
            'connect_timeout': self.connect_timeout
        }


# Global database configuration instance
db_config = DatabaseConfig()


def get_db_connection() -> Optional[psycopg2.extensions.connection]:
    """Establish database connection with comprehensive error handling.
    
    Returns:
        Database connection object or None if connection fails.
        
    Raises:
        No exceptions are raised; errors are logged and None is returned.
    """
    try:
        conn = psycopg2.connect(**db_config.get_connection_params())
        # Set connection to autocommit=False for explicit transaction control
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as e:
        print(f"Database operational error: {e}")
        return None
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected database connection error: {e}")
        return None


def validate_sensor_data(temperature: Any, humidity: Any) -> Tuple[bool, str, Optional[Tuple[float, float]]]:
    """Validate temperature and humidity sensor data.
    
    Args:
        temperature: Temperature value to validate
        humidity: Humidity value to validate
        
    Returns:
        Tuple of (is_valid, error_message, validated_data)
    """
    try:
        temp_float = float(temperature)
        humidity_float = float(humidity)
        
        if not (MIN_TEMPERATURE <= temp_float <= MAX_TEMPERATURE):
            return False, f"Temperatur skal være mellem {MIN_TEMPERATURE} og {MAX_TEMPERATURE}°C", None
            
        if not (MIN_HUMIDITY <= humidity_float <= MAX_HUMIDITY):
            return False, f"Fugtighed skal være mellem {MIN_HUMIDITY} og {MAX_HUMIDITY}%", None
            
        return True, "", (temp_float, humidity_float)
        
    except (ValueError, TypeError):
        return False, "Temperatur og fugtighed skal være numeriske værdier", None


def calculate_window_status(temperature: float, humidity: float) -> Dict[str, Any]:
    """Calculate window status based on ESP32 logic.
    
    This function uses the same logic as the ESP32 to determine if the window
    should be open or closed based on temperature and humidity thresholds.
    
    Args:
        temperature: Current temperature in Celsius
        humidity: Current humidity percentage
        
    Returns:
        Dict containing window status information
    """
    # Same logic as ESP32: should_open = (temperature > TEMP_THRESHOLD) or (humidity > HUMIDITY_THRESHOLD)
    should_open = (temperature > WINDOW_TEMP_THRESHOLD) or (humidity > WINDOW_HUMIDITY_THRESHOLD)
    
    status = "Åben" if should_open else "Lukket"
    reason = []
    
    if temperature > WINDOW_TEMP_THRESHOLD:
        reason.append(f"Temp {temperature}°C > {WINDOW_TEMP_THRESHOLD}°C")
    if humidity > WINDOW_HUMIDITY_THRESHOLD:
        reason.append(f"Fugt {humidity}% > {WINDOW_HUMIDITY_THRESHOLD}%")
    
    if not reason:
        reason.append("Normale værdier")
    
    return {
        'status': status,
        'should_open': should_open,
        'reason': " | ".join(reason),
        'temp_trigger': temperature > WINDOW_TEMP_THRESHOLD,
        'humidity_trigger': humidity > WINDOW_HUMIDITY_THRESHOLD
    }

# --- AUTHENTICATION AND VALIDATION ---
def login_required(func):
    """Decorator to require user authentication for protected routes.
    
    This decorator ensures that only authenticated users can access protected
    routes. It logs unauthorized access attempts for security monitoring.
    
    Args:
        func: The route function to protect
        
    Returns:
        Wrapped function that checks authentication before executing
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            print(f"Unauthorized access attempt to {func.__name__} from IP: {request.remote_addr}")
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper


def validate_input(data: str, max_length: int = MAX_INPUT_LENGTH) -> Tuple[bool, str]:
    """Validate user input for security and length constraints.
    
    Args:
        data: Input string to validate
        max_length: Maximum allowed length
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not data or not data.strip():
        return False, "Input må ikke være tom"
        
    if len(data) > max_length:
        return False, f"Input må maksimalt være {max_length} tegn"
        
    return True, ""

# --- ROUTES ---
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user authentication with comprehensive security measures.
    
    This function implements secure login with input validation, logging,
    and proper error handling. It includes protection against common
    web vulnerabilities and provides detailed security logging.
    
    Returns:
        Flask Response: Rendered template or redirect response
    """
    if request.method == "POST":
        # henter vores username og password fra formen
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        # validerer vores input for password og username
        username_valid, username_error = validate_input(username)
        password_valid, password_error = validate_input(password)
        
        if not username_valid:
            return render_template("login.html", error=username_error)
            
        if not password_valid:
            return render_template("login.html", error=password_error)

        # prøver at få database forbindelse
        conn = get_db_connection()
        if not conn:
            return render_template("login.html", error="Database forbindelsesfejl")
        
        try:
            with conn.cursor() as cur:
                # Secure parameterized query to prevent SQL injection
                cur.execute(
                    "SELECT id, username, password FROM users WHERE username = %s", 
                    (username,)
                )
                user_record = cur.fetchone()
                
                if user_record:
                    user_id, db_username, db_password = user_record
                    
                    
                    if password == db_password:
                       
                        session["user"] = db_username
                        session["user_id"] = user_id
                        session.permanent = True
                        
                        return redirect(url_for("home"))
                    else:
                        return render_template("login.html", error="Forkert brugernavn eller password")
                else:
                    # Generic error message to prevent username enumeration
                    return render_template("login.html", error="Forkert brugernavn eller password")
                    
        except psycopg2.Error as e:
            print(f"Database fejl under autentificering: {e}")
            return render_template("login.html", error="Der opstod en systemfejl")
        except Exception as e:
            print(f"Uventet fejl under autentificering: {e}")
            return render_template("login.html", error="Der opstod en uventet fejl")
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

@app.route("/bevægelse")
@login_required
def bevaegelse():
    """viser bevægelsesdetektering data fra PIR sensor.
    
    Returnere:
        Rendered template med bevægelsesdata
    """
    conn = get_db_connection()
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
    """viser temperature and fugtighed data from sensors.
    
    Returnere:
        Rendered template med miljødata
    """
    conn = get_db_connection()
    environment_data = []
    
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT timestamp, temperatur, fugtighed FROM temp_fugt ORDER BY timestamp DESC")
            rows = cur.fetchall()
            
            for row in rows:
                timestamp, temperature, humidity = row
                
                # vi beregner vindues status via vores esp32 logik som beregner det da det ikke gemmes på databasen
                window_info = calculate_window_status(temperature, humidity)
                
                environment_data.append({
                    'date': timestamp,
                    'temperature': temperature, 
                    'humidity': humidity,
                    'window_status': window_info['status'],
                    'window_reason': window_info['reason'],
                    'temp_trigger': window_info['temp_trigger'],
                    'humidity_trigger': window_info['humidity_trigger']
                })
        except psycopg2.Error as e:
            print(f"Database fejl: {e}")
        finally:
            conn.close()
            
    return render_template("tempertur_fugt.html", environment_data=environment_data)

@app.route("/door_control")
@login_required
def door_control():
    """hoveddør bliver status set om døren er open eller lukket.
    sammen med at den bruger comit til at sender signaler
    som åbner og lukker vores hoveddør 
    """
    conn = get_db_connection()
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
    """API endpoint for receiving temperature and fugtighed data fra ESP32 sensors.
    
    Dette endpoint validerer indkommende sensordata, sikrer dataintegritet,
    og gemmer gyldige målinger i databasen med omfattende fejlhåndtering.
    
    Returnere:
        JSON response med succes-/fejlmeddelelse og passende HTTP-statuskode
    """
    try:
        # json request fejlhåndtering hvis nu den ikke får modtaget data eller får en null fil f,eks
        data = request.get_json(force=True)
        
        if not data:
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        # bruger vores nødvendige områder 
        temperatur = data.get("temperatur")
        fugtighed = data.get("fugtighed") 
        timestamp = data.get("timestamp")

        # Validatere nødvendige felter tilstedeværelse
        if temperatur is None or fugtighed is None or timestamp is None:
            return jsonify({"error": "Mangler påkrævede felter (temperatur, fugtighed, timestamp)"}), 400
        
        # Validate sensor data using helper function
        is_valid, error_msg, validated_data = validate_sensor_data(temperatur, fugtighed)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
            
        temp_float, humidity_float = validated_data
        
        # Validatere timestamp format
        if not isinstance(timestamp, str) or len(timestamp.strip()) == 0:
            return jsonify({"error": "Ugyldig timestamp format"}), 400
        
        # Database operationer med transaktionshåndtering
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO temp_fugt (temperatur, fugtighed, timestamp) VALUES (%s, %s, %s)",
                    (temp_float, humidity_float, timestamp.strip())
                )
            conn.commit()
            
            print(f"Sensor data stored: {temp_float}°C, {humidity_float}%, {timestamp}")
            return jsonify({"message": "Sensordata gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database fejl i temp_fugt API: {e}")
            conn.rollback()
            return jsonify({"error": "Database fejl ved lagring"}), 500
        except Exception as e:
            print(f"Uventet fejl i temp_fugt API: {e}")
            conn.rollback()
            return jsonify({"error": "Uventet server fejl"}), 500
        finally:
            conn.close()
            
    except (ValueError, TypeError) as e:
        print(f"Ugyldig JSON data: {e}")
        return jsonify({"error": "Ugyldig JSON format"}), 400
    except Exception as e:
        print(f"Kritisk fejl i temp_fugt API: {e}")
        return jsonify({"error": "Kritisk server fejl"}), 500

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
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                movement_bool = bool(pir_value)
                cur.execute(
                    "INSERT INTO bevaegelse (beveagelse, timestamp) VALUES (%s, %s)",
                    (movement_bool, timestamp)
                )
            conn.commit()
            
            movement_text = "Bevægelse detekteret" if movement_bool else "Ingen bevægelse"
            print(f"PIR data received: {movement_text} ({movement_bool}), {timestamp}")
            return jsonify({"message": "Bevægelse data gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database fejl i PIR API: {e}")
            conn.rollback()
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
        
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                is_open = True if action == "open" else False
                cur.execute(
                    "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, NOW())",
                    (is_open,)
                )
            conn.commit()
            
            print(f"Solenoid command received: {action} -> {is_open}")
            return jsonify({"message": f"Dør kommando sendt: {action}"}), 200
        
        except psycopg2.Error as e:
            print(f"Database error in solenoid API: {e}")
            conn.rollback()
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500


@app.route("/api/solenoid/check", methods=["GET"])
def api_solenoid_check():
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                # Check for recent commands within timeout window
                cur.execute("""
                    SELECT is_the_door_open, timestamp, id
                    FROM door 
                    WHERE timestamp > NOW() - INTERVAL %s
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """, (f"{COMMAND_TIMEOUT_SECONDS} seconds",))
                result = cur.fetchone()
                
                if result:
                    command = "open" if result[0] else "close"
                    
                    # markere kommandoen som hentet ved at justere timestamp tilbage
                    cur.execute("""
                        UPDATE door 
                        SET timestamp = timestamp - INTERVAL '1 hour'
                        WHERE id = %s
                    """, (result[2],))
                    conn.commit()
                    
                    print(f"ESP32 command retrieved: {command} (ID: {result[2]})")
                    return jsonify({"command": command}), 200
                
                return jsonify({"command": None}), 200
        
        except psycopg2.Error as e:
            print(f"Database fejl i solenoid check API: {e}")
            conn.rollback()
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
        
        
        # Normalisere boolske værdier
        if isinstance(is_open, int):
            is_open = bool(is_open)
        elif isinstance(is_open, str):
            is_open = is_open.lower() in ('true', '1', 'yes', 'on')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, %s)",
                    (is_open, timestamp)
                )
            conn.commit()
            
            status_text = "Åben" if is_open else "Lukket"
            print(f"Door status logged: {status_text} ({is_open}), {timestamp}")
            return jsonify({"message": "Dør status gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            print(f"Database error in door log API: {e}")
            conn.rollback()
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500




# --- APPLICATION STARTUP ---
def init_app() -> None:
    """Initializere applikationen med opstartstjek og konfiguration."""
    print("Starter Mind Care overvågning System")
    
    # Test database connection at startup
    conn = get_db_connection()
    if conn:
        print("Database forbindelse succesfuld ved opstart")
        conn.close()
    else:
        print("Database forbindelse fejlede ved opstart")
        raise RuntimeError("Kan ikke starte applikationen uden database forbindelse")
    
    print(f"Applikation konfigureret med database: {db_config.dbname}@{db_config.host}:{db_config.port}")
    print("Mind Care overvågning System startet succesfuldt")


if __name__ == "__main__":
    try:
        init_app()
        app.run(
            host="0.0.0.0", 
            port=int(os.environ.get('PORT', 5000)),
            debug=os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
        )
    except Exception as e:
        print(f"Fejlede at starte applikationen: {e}")
        raise


