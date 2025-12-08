"""Health Monitoring System Flask Application.

A Flask web application for monitoring health data from ESP32 sensors,
including PIR motion detection, temperature/humidity monitoring, and
solenoid door control.

This application follows PEP8 standards and professional coding practices:
- Comprehensive error handling and logging
- Input validation and sanitization
- Type hints for better code documentation
- Modular design for maintainability
- Security considerations
"""

import os
import logging
from typing import Optional, Dict, Any, List, Tuple
from functools import wraps

import psycopg2
import psycopg2.extensions
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

# Configure logging with proper formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('health_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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


class DatabaseConfig:
    """Database configuration class for centralized configuration management.
    
    This class encapsulates all database configuration parameters and provides
    a single point of configuration management with environment variable support.
    """
    
    def __init__(self) -> None:
        """Initialize database configuration from environment variables."""
        self.dbname: str = os.environ.get('DB_NAME', 'health')
        self.user: str = os.environ.get('DB_USER', 'postgres')
        self.password: str = os.environ.get('DB_PASSWORD', 'demens')
        self.host: str = os.environ.get('DB_HOST', 'localhost')
        self.port: str = os.environ.get('DB_PORT', '5432')
        self.connect_timeout: int = int(os.environ.get('DB_TIMEOUT', '10'))

    def get_connection_params(self) -> Dict[str, Any]:
        """Get database connection parameters as dictionary.
        
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
        logger.error(f"Database operational error: {e}")
        return None
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected database connection error: {e}")
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
            logger.warning(
                f"Unauthorized access attempt to {func.__name__} "
                f"from IP: {request.remote_addr}"
            )
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
        # Extract and sanitize input data
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        # Comprehensive input validation
        username_valid, username_error = validate_input(username)
        password_valid, password_error = validate_input(password)
        
        if not username_valid:
            logger.warning(
                f"Invalid username input from IP: {request.remote_addr} - {username_error}"
            )
            return render_template("login.html", error=username_error)
            
        if not password_valid:
            logger.warning(
                f"Invalid password input from IP: {request.remote_addr} - {password_error}"
            )
            return render_template("login.html", error=password_error)

        # prøver at få database connection
        conn = get_db_connection()
        if not conn:
            logger.error("Database connection failed during login attempt")
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
                        
                        logger.info(f"Successful authentication for user: {username}")
                        return redirect(url_for("home"))
                    else:
                        logger.warning(
                            f"Failed authentication attempt for user: {username} "
                            f"from IP: {request.remote_addr}"
                        )
                        return render_template("login.html", error="Forkert brugernavn eller password")
                else:
                    logger.warning(
                        f"Authentication attempt for non-existent user: {username} "
                        f"from IP: {request.remote_addr}"
                    )
                    # Generic error message to prevent username enumeration
                    return render_template("login.html", error="Forkert brugernavn eller password")
                    
        except psycopg2.Error as e:
            logger.error(f"Database error during authentication: {e}")
            return render_template("login.html", error="Der opstod en systemfejl")
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
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
    """Display movement detection data from PIR sensor.
    
    Returns:
        Rendered template with movement data
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
    """Display temperature and humidity data from sensors.
    
    Returns:
        Rendered template with environment data
    """
    conn = get_db_connection()
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
    """Display door control interface with current door status.
    
    Returns:
        Rendered template with door status
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
    """API endpoint for receiving temperature and humidity data from ESP32 sensors.
    
    This endpoint validates incoming sensor data, ensures data integrity,
    and stores valid measurements in the database with comprehensive error handling.
    
    Expected JSON payload:
        {
            "temperatur": float,  # Temperature in Celsius (-50 to 100)
            "fugtighed": float,   # Humidity percentage (0 to 100)
            "timestamp": str      # ISO format timestamp
        }
    
    Returns:
        JSON response with success/error message and appropriate HTTP status code
    """
    try:
        # Extract JSON data with error handling
        data = request.get_json(force=True)
        
        if not data:
            logger.warning(f"Empty JSON payload received from {request.remote_addr}")
            return jsonify({"error": "Ingen data modtaget"}), 400
            
        # Extract required fields
        temperatur = data.get("temperatur")
        fugtighed = data.get("fugtighed") 
        timestamp = data.get("timestamp")

        # Validate required fields presence
        if temperatur is None or fugtighed is None or timestamp is None:
            logger.warning(
                f"Missing required fields in sensor data from {request.remote_addr}: "
                f"temp={temperatur}, humidity={fugtighed}, timestamp={timestamp}"
            )
            return jsonify({"error": "Mangler påkrævede felter (temperatur, fugtighed, timestamp)"}), 400
        
        # Validate sensor data using helper function
        is_valid, error_msg, validated_data = validate_sensor_data(temperatur, fugtighed)
        if not is_valid:
            logger.warning(f"Invalid sensor data from {request.remote_addr}: {error_msg}")
            return jsonify({"error": error_msg}), 400
            
        temp_float, humidity_float = validated_data
        
        # Validate timestamp format (basic check)
        if not isinstance(timestamp, str) or len(timestamp.strip()) == 0:
            return jsonify({"error": "Ugyldig timestamp format"}), 400
        
        # Database operations with transaction handling
        conn = get_db_connection()
        if not conn:
            logger.error("Database connection failed in temp_fugt API")
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO temp_fugt (temperatur, fugtighed, timestamp) VALUES (%s, %s, %s)",
                    (temp_float, humidity_float, timestamp.strip())
                )
            conn.commit()
            
            logger.info(
                f"Sensor data stored successfully: {temp_float}°C, {humidity_float}%, "
                f"timestamp={timestamp} from {request.remote_addr}"
            )
            return jsonify({"message": "Sensordata gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            logger.error(f"Database error in temp_fugt API: {e}")
            conn.rollback()
            return jsonify({"error": "Database fejl ved lagring"}), 500
        except Exception as e:
            logger.error(f"Unexpected error in temp_fugt API: {e}")
            conn.rollback()
            return jsonify({"error": "Uventet server fejl"}), 500
        finally:
            conn.close()
            
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid JSON data from {request.remote_addr}: {e}")
        return jsonify({"error": "Ugyldig JSON format"}), 400
    except Exception as e:
        logger.error(f"Critical error in temp_fugt API: {e}")
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
            logger.error("Database connection failed in PIR API")
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
            logger.info(f"PIR data received: {movement_text} ({movement_bool}), {timestamp}")
            return jsonify({"message": "Bevægelse data gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            logger.error(f"Database error in PIR API: {e}")
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
            logger.error("Database connection failed in solenoid API")
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                is_open = True if action == "open" else False
                cur.execute(
                    "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, NOW())",
                    (is_open,)
                )
            conn.commit()
            
            logger.info(f"Solenoid command received: {action} -> {is_open}")
            return jsonify({"message": f"Dør kommando sendt: {action}"}), 200
        
        except psycopg2.Error as e:
            logger.error(f"Database error in solenoid API: {e}")
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
            logger.error("Database connection failed in solenoid check API")
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
                    
                    # Mark command as processed by updating timestamp
                    cur.execute("""
                        UPDATE door 
                        SET timestamp = timestamp - INTERVAL '1 hour'
                        WHERE id = %s
                    """, (result[2],))
                    conn.commit()
                    
                    logger.info(f"ESP32 command retrieved: {command} (ID: {result[2]})")
                    return jsonify({"command": command}), 200
                
                return jsonify({"command": None}), 200
        
        except psycopg2.Error as e:
            logger.error(f"Database error in solenoid check API: {e}")
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
        
        
        # Normalize boolean values
        if isinstance(is_open, int):
            is_open = bool(is_open)
        elif isinstance(is_open, str):
            is_open = is_open.lower() in ('true', '1', 'yes', 'on')
        
        conn = get_db_connection()
        if not conn:
            logger.error("Database connection failed in door log API")
            return jsonify({"error": "Database forbindelsesfejl"}), 500
            
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO door (is_the_door_open, timestamp) VALUES (%s, %s)",
                    (is_open, timestamp)
                )
            conn.commit()
            
            status_text = "Åben" if is_open else "Lukket"
            logger.info(f"Door status logged: {status_text} ({is_open}), {timestamp}")
            return jsonify({"message": "Dør status gemt succesfuldt"}), 201
        
        except psycopg2.Error as e:
            logger.error(f"Database error in door log API: {e}")
            conn.rollback()
            return jsonify({"error": "Database fejl"}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"API fejl: {e}")
        return jsonify({"error": "Server fejl"}), 500

# --- ERROR HANDLERS ---
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    logger.warning(f"404 error: {request.url} from {request.remote_addr}")
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"500 error: {error} from {request.remote_addr}")
    return render_template('500.html'), 500


@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 errors."""
    logger.warning(f"403 error: Forbidden access from {request.remote_addr}")
    return render_template('403.html'), 403


# --- APPLICATION STARTUP ---
def init_app() -> None:
    """Initialize application with startup checks and configuration."""
    logger.info("Starting Health Monitoring System")
    
    # Test database connection at startup
    conn = get_db_connection()
    if conn:
        logger.info("Database connection successful at startup")
        conn.close()
    else:
        logger.error("Failed to connect to database at startup")
        raise RuntimeError("Cannot start application without database connection")
    
    # Log configuration
    logger.info(f"Application configured with database: {db_config.dbname}@{db_config.host}:{db_config.port}")
    logger.info("Health Monitoring System started successfully")


if __name__ == "__main__":
    try:
        init_app()
        app.run(
            host="0.0.0.0", 
            port=int(os.environ.get('PORT', 5000)),
            debug=os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
        )
    except Exception as e:
        logger.critical(f"Failed to start application: {e}")
        raise


