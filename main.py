from flask import Flask, render_template, request, redirect, url_for, session
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
            dbname=os.environ.get('DB_NAME', 'login_credentials'),
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

# --- START APP ---
if __name__ == "__main__":
    app.run(debug=True)
