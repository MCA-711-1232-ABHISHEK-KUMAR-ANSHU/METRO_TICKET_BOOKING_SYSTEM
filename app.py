from flask import Flask, request, jsonify, render_template, redirect, session, send_file, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import mysql.connector
import qrcode
import os

from reportlab.lib.pagesizes import A6
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

app = Flask(__name__)
app.secret_key = "metro-ticket-system-secret-key"   # change this in production

QR_FOLDER = os.path.join("static", "qrcodes")
PDF_FOLDER = os.path.join("static", "pdfs")
os.makedirs(QR_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)


# =====================================================
# DATABASE HELPER
# =====================================================
# NOTE: a single global connection (as in the original code) eventually
# drops/times out and breaks every route. We open a fresh connection
# for every request instead and always close it afterwards.

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",        # <-- put your MySQL password here
        database="metro_db"
    )


def run_query(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())

    result = None
    if fetchone:
        result = cursor.fetchone()
    elif fetchall:
        result = cursor.fetchall()

    last_id = cursor.lastrowid

    if commit:
        conn.commit()

    cursor.close()
    conn.close()

    return result, last_id


# =====================================================
# SMALL HELPERS
# =====================================================

def is_logged_in():
    return "passenger_id" in session


def is_admin():
    return "admin_id" in session


def calculate_fare(from_station, to_station):
    """Look up a fare from the admin-defined routes table.
    Falls back to a simple distance-based formula if no matching
    route has been configured by the admin yet."""

    route, _ = run_query(
        """
        SELECT fare FROM route
        WHERE (start_station=%s AND end_station=%s)
           OR (start_station=%s AND end_station=%s)
        ORDER BY route_id LIMIT 1
        """,
        (from_station, to_station, to_station, from_station),
        fetchone=True
    )

    if route:
        return route["fare"]

    return abs(int(to_station) - int(from_station)) * 10


def calculate_refund(travel_date, fare):
    """Compensation policy for cancelled tickets:
       - more than 1 day before travel  -> 80% refund
       - on the day of / 1 day before   -> 50% refund
       - travel date already passed     -> no refund
    """
    if isinstance(travel_date, str):
        travel_date = datetime.strptime(travel_date, "%Y-%m-%d").date()

    days_left = (travel_date - date.today()).days

    if days_left > 1:
        return int(fare * 0.8)
    elif days_left >= 0:
        return int(fare * 0.5)
    else:
        return 0


def generate_qr(ticket_id, from_station, to_station):
    qr_data = f"METROTICKET:{ticket_id}"
    img = qrcode.make(qr_data)
    qr_path = os.path.join(QR_FOLDER, f"qr_{ticket_id}.png")
    img.save(qr_path)
    return qr_path


def generate_ticket_pdf(ticket):
    pdf_path = os.path.join(PDF_FOLDER, f"ticket_{ticket['ticket_id']}.pdf")

    c = canvas.Canvas(pdf_path, pagesize=A6)
    width, height = A6

    c.setFillColorRGB(0.04, 0.24, 0.38)
    c.rect(0, height - 20 * mm, width, 20 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 13 * mm, "Patna Metro - E-Ticket")

    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)

    rows = [
        ("Ticket ID", str(ticket["ticket_id"])),
        ("From", ticket["from_station"]),
        ("To", ticket["to_station"]),
        ("Travel Date", str(ticket["travel_date"])),
        ("Fare", f"Rs. {ticket['fare']}"),
        ("Status", ticket.get("status", "BOOKED")),
    ]

    y = height - 30 * mm
    for label, value in rows:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(8 * mm, y, f"{label}:")
        c.setFont("Helvetica", 9)
        c.drawString(32 * mm, y, value)
        y -= 6.5 * mm

    qr_path = os.path.join(QR_FOLDER, f"qr_{ticket['ticket_id']}.png")
    if os.path.exists(qr_path):
        qr_size = 32 * mm
        c.drawImage(qr_path, (width - qr_size) / 2, y - qr_size - 4 * mm, width=qr_size, height=qr_size)
        y -= (qr_size + 8 * mm)

    c.setFont("Helvetica-Oblique", 7)
    footer_y = max(y - 8 * mm, 10 * mm)
    c.drawCentredString(width / 2, footer_y, "Show this QR code at the metro gate.")
    c.drawCentredString(width / 2, footer_y - 5 * mm, "Keep it safe for the entire journey.")

    c.save()
    return pdf_path


# =====================================================
# PUBLIC PAGES
# =====================================================

@app.route("/")
def home():
    return render_template("home.html", logged_in=is_logged_in())


@app.route("/contact-page")
def contact_page():
    return render_template("contact.html")


@app.route("/contact", methods=["POST"])
def contact():
    data = request.get_json()

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return jsonify({"message": "Name, email and message are required"}), 400

    run_query(
        "INSERT INTO contact_message(name,email,subject,message) VALUES(%s,%s,%s,%s)",
        (name, email, subject, message),
        commit=True
    )

    return jsonify({"message": "Thank you, we have received your message"})


@app.route("/search-ticket-page")
def search_ticket_page():
    return render_template("search_ticket.html")


@app.route("/search-ticket", methods=["POST"])
def search_ticket():
    data = request.get_json()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        return jsonify({"message": "Ticket ID is required"}), 400

    return jsonify({"redirect": f"/ticket/{ticket_id}"})


# =====================================================
# AUTH
# =====================================================

@app.route("/register-page")
def register_page():
    return render_template("register.html")


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()

    if not username or not email or not password:
        return jsonify({"message": "All fields are required"}), 400

    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters"}), 400

    existing, _ = run_query(
        "SELECT user_id FROM user WHERE email=%s OR username=%s",
        (email, username), fetchone=True
    )
    if existing:
        return jsonify({"message": "Username or email already registered"}), 400

    hashed_password = generate_password_hash(password)

    _, user_id = run_query(
        "INSERT INTO user(username,email,password) VALUES(%s,%s,%s)",
        (username, email, hashed_password), commit=True
    )

    run_query(
        "INSERT INTO passenger(user_id,name,phone) VALUES(%s,%s,%s)",
        (user_id, username, phone), commit=True
    )

    return jsonify({"message": "User registered successfully"})


@app.route("/login-page")
def login_page():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    user, _ = run_query(
        """
        SELECT u.user_id, u.password, u.role, p.passenger_id, p.name
        FROM user u
        JOIN passenger p ON u.user_id = p.user_id
        WHERE u.email=%s
        """,
        (email,), fetchone=True
    )

    if user and check_password_hash(user["password"], password):
        session["passenger_id"] = user["passenger_id"]
        session["user_id"] = user["user_id"]
        session["name"] = user["name"]

        return jsonify({
            "message": "Login successful",
            "user": {"passenger_id": user["passenger_id"], "name": user["name"]}
        })

    return jsonify({"message": "Invalid email or password"}), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/forgot-password-page")
def forgot_password_page():
    return render_template("forgot_password.html")


@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    """Simplified flow for the academic project: since there is no mail
    server configured, the user verifies their email + username and is
    then allowed to directly set a new password."""
    data = request.get_json()

    email = (data.get("email") or "").strip()
    username = (data.get("username") or "").strip()
    new_password = data.get("new_password") or ""

    if not email or not username or not new_password:
        return jsonify({"message": "All fields are required"}), 400

    if len(new_password) < 6:
        return jsonify({"message": "Password must be at least 6 characters"}), 400

    user, _ = run_query(
        "SELECT user_id FROM user WHERE email=%s AND username=%s",
        (email, username), fetchone=True
    )

    if not user:
        return jsonify({"message": "No matching account found"}), 404

    run_query(
        "UPDATE user SET password=%s WHERE user_id=%s",
        (generate_password_hash(new_password), user["user_id"]), commit=True
    )

    return jsonify({"message": "Password updated. Please login."})


# =====================================================
# CUSTOMER DASHBOARD MODULE
# =====================================================

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login-page")

    passenger_id = session["passenger_id"]

    stats, _ = run_query(
        """
        SELECT
          COUNT(*) AS total_tickets,
          SUM(CASE WHEN status='BOOKED' THEN 1 ELSE 0 END) AS upcoming,
          SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
          SUM(CASE WHEN status='USED' THEN 1 ELSE 0 END) AS completed
        FROM ticket WHERE passenger_id=%s
        """,
        (passenger_id,), fetchone=True
    )

    recent, _ = run_query(
        """
        SELECT t.ticket_id, s1.station_name AS from_station,
               s2.station_name AS to_station, t.travel_date, t.fare, t.status
        FROM ticket t
        JOIN station s1 ON t.from_station = s1.station_id
        JOIN station s2 ON t.to_station = s2.station_id
        WHERE t.passenger_id=%s
        ORDER BY t.ticket_id DESC LIMIT 5
        """,
        (passenger_id,), fetchall=True
    )

    return render_template("dashboard.html", name=session.get("name"), stats=stats, recent=recent)


@app.route("/edit-profile-page")
def edit_profile_page():
    if not is_logged_in():
        return redirect("/login-page")

    passenger, _ = run_query(
        "SELECT name, phone FROM passenger WHERE passenger_id=%s",
        (session["passenger_id"],), fetchone=True
    )
    return render_template("edit_profile.html", passenger=passenger)


@app.route("/edit-profile", methods=["POST"])
def edit_profile():
    if not is_logged_in():
        return jsonify({"message": "Please login first"}), 401

    data = request.get_json()
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not name:
        return jsonify({"message": "Name is required"}), 400

    run_query(
        "UPDATE passenger SET name=%s, phone=%s WHERE passenger_id=%s",
        (name, phone, session["passenger_id"]), commit=True
    )
    session["name"] = name

    return jsonify({"message": "Profile updated successfully"})


@app.route("/change-password-page")
def change_password_page():
    if not is_logged_in():
        return redirect("/login-page")
    return render_template("change_password.html")


@app.route("/change-password", methods=["POST"])
def change_password():
    if not is_logged_in():
        return jsonify({"message": "Please login first"}), 401

    data = request.get_json()
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""

    if len(new_password) < 6:
        return jsonify({"message": "New password must be at least 6 characters"}), 400

    user, _ = run_query(
        "SELECT password FROM user WHERE user_id=%s",
        (session["user_id"],), fetchone=True
    )

    if not user or not check_password_hash(user["password"], old_password):
        return jsonify({"message": "Old password is incorrect"}), 400

    run_query(
        "UPDATE user SET password=%s WHERE user_id=%s",
        (generate_password_hash(new_password), session["user_id"]), commit=True
    )

    return jsonify({"message": "Password changed successfully"})


@app.route("/feedback-page")
def feedback_page():
    if not is_logged_in():
        return redirect("/login-page")
    return render_template("feedback.html")


@app.route("/feedback", methods=["POST"])
def feedback():
    if not is_logged_in():
        return jsonify({"message": "Please login first"}), 401

    data = request.get_json()
    message = (data.get("message") or "").strip()
    rating = data.get("rating")

    if not message:
        return jsonify({"message": "Feedback message is required"}), 400

    run_query(
        "INSERT INTO feedback(passenger_id, message, rating) VALUES(%s,%s,%s)",
        (session["passenger_id"], message, rating), commit=True
    )

    return jsonify({"message": "Thank you for your feedback"})


# =====================================================
# STATIONS
# =====================================================

@app.route("/stations")
def stations():
    rows, _ = run_query("SELECT * FROM station ORDER BY station_name", fetchall=True)
    return jsonify(rows)


# =====================================================
# BOOKING
# =====================================================

@app.route("/book-page")
def book_page():
    if not is_logged_in():
        return redirect("/login-page")
    return render_template("book_ticket.html")


@app.route("/book-ticket", methods=["POST"])
def book_ticket():
    if not is_logged_in():
        return jsonify({"message": "Please login first"}), 401

    data = request.get_json()

    passenger_id = session["passenger_id"]
    from_station = data.get("from_station")
    to_station = data.get("to_station")
    travel_date = data.get("travel_date")

    if not from_station or not to_station or not travel_date:
        return jsonify({"message": "All fields are required"}), 400

    if from_station == to_station:
        return jsonify({"message": "From and To stations cannot be the same"}), 400

    try:
        travel_date_obj = datetime.strptime(travel_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"message": "Invalid travel date"}), 400

    if travel_date_obj < date.today():
        return jsonify({"message": "Travel date cannot be in the past"}), 400

    fare = calculate_fare(from_station, to_station)

    _, ticket_id = run_query(
        """
        INSERT INTO ticket(passenger_id,from_station,to_station,travel_date,fare,status)
        VALUES(%s,%s,%s,%s,%s,'BOOKED')
        """,
        (passenger_id, from_station, to_station, travel_date, fare), commit=True
    )

    run_query(
        "INSERT INTO payment(ticket_id, amount, payment_method, payment_status) VALUES(%s,%s,%s,%s)",
        (ticket_id, fare, "ONLINE", "PAID"), commit=True
    )

    generate_qr(ticket_id, from_station, to_station)

    return jsonify({
        "message": "Ticket booked successfully",
        "ticket_id": ticket_id,
        "fare": fare
    })


def get_ticket_or_none(ticket_id):
    return run_query(
        """
        SELECT t.ticket_id, t.passenger_id,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               t.travel_date, t.fare, t.status
        FROM ticket t
        JOIN station s1 ON t.from_station = s1.station_id
        JOIN station s2 ON t.to_station = s2.station_id
        WHERE t.ticket_id=%s
        """,
        (ticket_id,), fetchone=True
    )[0]


@app.route("/ticket/<int:ticket_id>")
def ticket_page(ticket_id):
    ticket = get_ticket_or_none(ticket_id)

    if not ticket:
        return render_template("404.html", reason="Ticket not found"), 404

    qr_path = os.path.join(QR_FOLDER, f"qr_{ticket_id}.png")
    if not os.path.exists(qr_path):
        generate_qr(ticket_id, ticket["from_station"], ticket["to_station"])

    return render_template("ticket.html", ticket=ticket, qr=qr_path)


@app.route("/ticket/<int:ticket_id>/pdf")
def ticket_pdf(ticket_id):
    ticket = get_ticket_or_none(ticket_id)

    if not ticket:
        return render_template("404.html", reason="Ticket not found"), 404

    pdf_path = generate_ticket_pdf(ticket)
    return send_file(pdf_path, as_attachment=True, download_name=f"metro_ticket_{ticket_id}.pdf")


@app.route("/my-tickets")
def my_tickets():
    if not is_logged_in():
        return redirect("/login-page")

    tickets, _ = run_query(
        """
        SELECT t.ticket_id, s1.station_name AS from_station,
               s2.station_name AS to_station, t.travel_date, t.fare, t.status
        FROM ticket t
        JOIN station s1 ON t.from_station = s1.station_id
        JOIN station s2 ON t.to_station = s2.station_id
        WHERE t.passenger_id=%s
        ORDER BY t.ticket_id DESC
        """,
        (session["passenger_id"],), fetchall=True
    )

    return render_template("tickets.html", tickets=tickets)


# =====================================================
# CANCELLATION + COMPENSATION
# =====================================================

@app.route("/cancel-ticket-page/<int:ticket_id>")
def cancel_ticket_page(ticket_id):
    if not is_logged_in():
        return redirect("/login-page")

    ticket = get_ticket_or_none(ticket_id)

    if not ticket or ticket["passenger_id"] != session["passenger_id"]:
        return render_template("404.html", reason="Ticket not found"), 404

    if ticket["status"] != "BOOKED":
        return render_template("404.html", reason="This ticket cannot be cancelled"), 400

    estimated_refund = calculate_refund(ticket["travel_date"], ticket["fare"])

    return render_template("cancel_ticket.html", ticket=ticket, estimated_refund=estimated_refund)


@app.route("/cancel-ticket/<int:ticket_id>", methods=["POST"])
def cancel_ticket(ticket_id):
    if not is_logged_in():
        return jsonify({"message": "Please login first"}), 401

    ticket = get_ticket_or_none(ticket_id)

    if not ticket or ticket["passenger_id"] != session["passenger_id"]:
        return jsonify({"message": "Ticket not found"}), 404

    if ticket["status"] != "BOOKED":
        return jsonify({"message": "This ticket cannot be cancelled"}), 400

    data = request.get_json() or {}
    reason = (data.get("reason") or "Not specified").strip()

    refund = calculate_refund(ticket["travel_date"], ticket["fare"])

    run_query("UPDATE ticket SET status='CANCELLED' WHERE ticket_id=%s", (ticket_id,), commit=True)

    run_query(
        "INSERT INTO cancellation(ticket_id, reason, refund_amount) VALUES(%s,%s,%s)",
        (ticket_id, reason, refund), commit=True
    )

    return jsonify({"message": "Ticket cancelled", "refund_amount": refund})


# =====================================================
# QR CODE SCANNER MODULE (used at the metro gate)
# =====================================================

@app.route("/scan-page")
def scan_page():
    return render_template("qr_scanner.html")


@app.route("/verify-ticket", methods=["POST"])
def verify_ticket():
    data = request.get_json()
    raw_value = str(data.get("ticket_data") or "").strip()

    # QR encodes "METROTICKET:<id>" -- also accept a plain numeric ID
    # so the manual-entry fallback form on the same page works too.
    ticket_id = None
    if raw_value.startswith("METROTICKET:"):
        ticket_id = raw_value.split(":")[1]
    elif raw_value.isdigit():
        ticket_id = raw_value

    if not ticket_id:
        return jsonify({"valid": False, "message": "Unrecognised QR code"}), 400

    ticket = get_ticket_or_none(ticket_id)

    if not ticket:
        return jsonify({"valid": False, "message": "Ticket does not exist"}), 404

    if ticket["status"] == "CANCELLED":
        return jsonify({"valid": False, "message": "This ticket was cancelled", "ticket": ticket})

    if ticket["status"] == "USED":
        return jsonify({"valid": False, "message": "This ticket has already been used", "ticket": ticket})

    run_query("UPDATE ticket SET status='USED' WHERE ticket_id=%s", (ticket_id,), commit=True)
    ticket["status"] = "USED"

    return jsonify({"valid": True, "message": "Entry approved", "ticket": ticket})


# =====================================================
# ADMIN MODULE
# =====================================================

@app.route("/admin-login-page")
def admin_login_page():
    return render_template("admin_login.html")


@app.route("/admin-login", methods=["POST"])
def admin_login():
    data = request.get_json()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    user, _ = run_query(
        "SELECT user_id, password, username FROM user WHERE email=%s AND role='admin'",
        (email,), fetchone=True
    )

    if user and check_password_hash(user["password"], password):
        session["admin_id"] = user["user_id"]
        session["admin_name"] = user["username"]
        return jsonify({"message": "Login successful"})

    return jsonify({"message": "Invalid admin credentials"}), 401


@app.route("/admin-logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    return redirect("/admin-login-page")


@app.route("/admin-dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect("/admin-login-page")

    stats, _ = run_query(
        """
        SELECT
          (SELECT COUNT(*) FROM ticket) AS total_tickets,
          (SELECT COUNT(*) FROM ticket WHERE status='BOOKED') AS active_tickets,
          (SELECT COUNT(*) FROM ticket WHERE status='CANCELLED') AS cancelled_tickets,
          (SELECT COALESCE(SUM(fare),0) FROM ticket WHERE status!='CANCELLED') AS total_revenue,
          (SELECT COUNT(*) FROM station) AS total_stations,
          (SELECT COUNT(*) FROM route) AS total_routes
        """,
        fetchone=True
    )

    return render_template("admin_dashboard.html", name=session.get("admin_name"), stats=stats)


# ---------- STATIONS ----------

@app.route("/admin/stations")
def admin_manage_stations():
    if not is_admin():
        return redirect("/admin-login-page")

    rows, _ = run_query("SELECT * FROM station ORDER BY station_id", fetchall=True)
    return render_template("admin_manage_stations.html", stations=rows)


@app.route("/admin/stations/add-page")
def admin_add_station_page():
    if not is_admin():
        return redirect("/admin-login-page")
    return render_template("admin_add_station.html")


@app.route("/admin/stations/add", methods=["POST"])
def admin_add_station():
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    data = request.get_json()
    name = (data.get("station_name") or "").strip()
    location = (data.get("location") or "").strip()

    if not name:
        return jsonify({"message": "Station name is required"}), 400

    run_query(
        "INSERT INTO station(station_name, location) VALUES(%s,%s)",
        (name, location), commit=True
    )

    return jsonify({"message": "Station added successfully"})


@app.route("/admin/stations/edit-page/<int:station_id>")
def admin_edit_station_page(station_id):
    if not is_admin():
        return redirect("/admin-login-page")

    station, _ = run_query("SELECT * FROM station WHERE station_id=%s", (station_id,), fetchone=True)
    return render_template("admin_edit_station.html", station=station)


@app.route("/admin/stations/edit/<int:station_id>", methods=["POST"])
def admin_edit_station(station_id):
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    data = request.get_json()
    name = (data.get("station_name") or "").strip()
    location = (data.get("location") or "").strip()

    if not name:
        return jsonify({"message": "Station name is required"}), 400

    run_query(
        "UPDATE station SET station_name=%s, location=%s WHERE station_id=%s",
        (name, location, station_id), commit=True
    )

    return jsonify({"message": "Station updated successfully"})


@app.route("/admin/stations/delete/<int:station_id>", methods=["POST"])
def admin_delete_station(station_id):
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    run_query("DELETE FROM station WHERE station_id=%s", (station_id,), commit=True)
    return jsonify({"message": "Station deleted"})


# ---------- ROUTES & FARES ----------

@app.route("/admin/routes")
def admin_manage_routes():
    if not is_admin():
        return redirect("/admin-login-page")

    rows, _ = run_query(
        """
        SELECT r.route_id, r.route_name, r.fare,
               s1.station_name AS start_station, s2.station_name AS end_station
        FROM route r
        JOIN station s1 ON r.start_station = s1.station_id
        JOIN station s2 ON r.end_station = s2.station_id
        ORDER BY r.route_id
        """,
        fetchall=True
    )
    return render_template("admin_manage_routes.html", routes=rows)


@app.route("/admin/routes/add-page")
def admin_add_route_page():
    if not is_admin():
        return redirect("/admin-login-page")

    stations, _ = run_query("SELECT * FROM station ORDER BY station_name", fetchall=True)
    return render_template("admin_add_route.html", stations=stations)


@app.route("/admin/routes/add", methods=["POST"])
def admin_add_route():
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    data = request.get_json()
    route_name = (data.get("route_name") or "").strip()
    start_station = data.get("start_station")
    end_station = data.get("end_station")
    fare = data.get("fare")

    if not route_name or not start_station or not end_station or fare is None:
        return jsonify({"message": "All fields are required"}), 400

    if start_station == end_station:
        return jsonify({"message": "Start and end stations cannot be the same"}), 400

    try:
        fare = int(fare)
        if fare < 0:
            raise ValueError
    except ValueError:
        return jsonify({"message": "Fare must be a positive number"}), 400

    run_query(
        "INSERT INTO route(route_name, start_station, end_station, fare) VALUES(%s,%s,%s,%s)",
        (route_name, start_station, end_station, fare), commit=True
    )

    return jsonify({"message": "Route added successfully"})


@app.route("/admin/routes/edit-page/<int:route_id>")
def admin_edit_route_page(route_id):
    if not is_admin():
        return redirect("/admin-login-page")

    route, _ = run_query("SELECT * FROM route WHERE route_id=%s", (route_id,), fetchone=True)
    stations, _ = run_query("SELECT * FROM station ORDER BY station_name", fetchall=True)
    return render_template("admin_edit_route.html", route=route, stations=stations)


@app.route("/admin/routes/edit/<int:route_id>", methods=["POST"])
def admin_edit_route(route_id):
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    data = request.get_json()
    route_name = (data.get("route_name") or "").strip()
    start_station = data.get("start_station")
    end_station = data.get("end_station")
    fare = data.get("fare")

    try:
        fare = int(fare)
        if fare < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"message": "Fare must be a positive number"}), 400

    run_query(
        "UPDATE route SET route_name=%s, start_station=%s, end_station=%s, fare=%s WHERE route_id=%s",
        (route_name, start_station, end_station, fare, route_id), commit=True
    )

    return jsonify({"message": "Route updated successfully"})


@app.route("/admin/routes/delete/<int:route_id>", methods=["POST"])
def admin_delete_route(route_id):
    if not is_admin():
        return jsonify({"message": "Admin login required"}), 401

    run_query("DELETE FROM route WHERE route_id=%s", (route_id,), commit=True)
    return jsonify({"message": "Route deleted"})


# ---------- BOOKINGS / CANCELLATIONS / REPORTS ----------

@app.route("/admin/bookings")
def admin_view_bookings():
    if not is_admin():
        return redirect("/admin-login-page")

    rows, _ = run_query(
        """
        SELECT t.ticket_id, p.name AS passenger_name,
               s1.station_name AS from_station, s2.station_name AS to_station,
               t.travel_date, t.fare, t.status
        FROM ticket t
        JOIN passenger p ON t.passenger_id = p.passenger_id
        JOIN station s1 ON t.from_station = s1.station_id
        JOIN station s2 ON t.to_station = s2.station_id
        ORDER BY t.ticket_id DESC
        """,
        fetchall=True
    )
    return render_template("admin_view_bookings.html", tickets=rows)


@app.route("/admin/cancellations")
def admin_view_cancellations():
    if not is_admin():
        return redirect("/admin-login-page")

    rows, _ = run_query(
        """
        SELECT c.cancellation_id, c.ticket_id, p.name AS passenger_name,
               c.reason, c.refund_amount, c.cancelled_on
        FROM cancellation c
        JOIN ticket t ON c.ticket_id = t.ticket_id
        JOIN passenger p ON t.passenger_id = p.passenger_id
        ORDER BY c.cancellation_id DESC
        """,
        fetchall=True
    )
    return render_template("admin_view_cancellations.html", cancellations=rows)


@app.route("/admin/reports")
def admin_reports():
    if not is_admin():
        return redirect("/admin-login-page")

    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = """
        SELECT t.ticket_id, t.travel_date, t.fare, t.status
        FROM ticket t
        WHERE t.status != 'CANCELLED'
    """
    params = []

    if start_date and end_date:
        query += " AND t.travel_date BETWEEN %s AND %s"
        params = [start_date, end_date]

    query += " ORDER BY t.travel_date DESC"

    rows, _ = run_query(query, params, fetchall=True)

    total_revenue = sum(r["fare"] for r in rows)

    return render_template(
        "admin_reports.html",
        tickets=rows,
        total_revenue=total_revenue,
        start_date=start_date or "",
        end_date=end_date or ""
    )


@app.route("/admin/feedback")
def admin_view_feedback():
    if not is_admin():
        return redirect("/admin-login-page")

    rating_filter = request.args.get("rating")

    query = """
        SELECT f.feedback_id, p.name AS passenger_name, f.message, f.rating, f.submitted_on
        FROM feedback f
        JOIN passenger p ON f.passenger_id = p.passenger_id
    """
    params = []

    if rating_filter:
        query += " WHERE f.rating = %s"
        params = [rating_filter]

    query += " ORDER BY f.feedback_id DESC"

    rows, _ = run_query(query, params, fetchall=True)

    return render_template("admin_view_feedback.html", feedback_list=rows, rating_filter=rating_filter or "")


@app.route("/admin/contact-messages")
def admin_view_contact_messages():
    if not is_admin():
        return redirect("/admin-login-page")

    email_filter = (request.args.get("email") or "").strip()

    query = "SELECT * FROM contact_message"
    params = []

    if email_filter:
        query += " WHERE email LIKE %s"
        params = [f"%{email_filter}%"]

    query += " ORDER BY message_id DESC"

    rows, _ = run_query(query, params, fetchall=True)

    return render_template("admin_view_contact.html", messages=rows, email_filter=email_filter)


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html", reason="Page not found"), 404


if __name__ == "__main__":
    app.run(debug=True)
