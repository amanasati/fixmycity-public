from flask import Flask, render_template, redirect, url_for, session, jsonify, request, flash
from authlib.integrations.flask_client import OAuth
import os
import base64
import json
import requests
from functools import wraps
from datetime import datetime
from pymongo import MongoClient
from imagekitio import ImageKit
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ── ImageKit Setup (SDK v5.3.0) ────────────────────────────────────────────────
IMAGEKIT_PUBLIC_KEY = os.getenv("IMAGEKIT_PUBLIC_KEY")
IMAGEKIT_URL_ENDPOINT = os.getenv("IMAGEKIT_URL_ENDPOINT")

imagekit = ImageKit(
    private_key=os.getenv("IMAGEKIT_PRIVATE_KEY")
)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cityproblem-secret-key-change-in-production")

# ── OAuth Setup ──────────────────────────────────────────────────────────────
try:
    oauth = OAuth(app)
    google = oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    OAUTH_AVAILABLE = True
except Exception as e:
    print(f"OAuth setup failed: {e}")
    OAUTH_AVAILABLE = False

# ── Auth helpers ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── MongoDB Connection ───────────────────────────────────────────────────────
try:
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    client.server_info()  # Force connection check
    db = client["cityproblem"]          # Database name
    complaints_col = db["complaints"]  # Complaints collection
    alerts_col = db["alerts"]          # Alerts collection
    MONGO_AVAILABLE = True
    print("✅ MongoDB connected successfully.")
except Exception as e:
    print(f"⚠️  MongoDB not available, falling back to in-memory storage: {e}")
    MONGO_AVAILABLE = False
    complaints_col = None
    alerts_col = None

# ── In-memory fallback ───────────────────────────────────────────────────────
COMPLAINTS = []
complaint_counter = 1

ALERTS = []
alert_counter = 1

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_complaints():
    if MONGO_AVAILABLE:
        return list(complaints_col.find({}, {"_id": 0}))
    return COMPLAINTS

def get_alerts():
    if MONGO_AVAILABLE:
        return list(alerts_col.find({}, {"_id": 0}))
    return ALERTS

# ── Helper functions ─────────────────────────────────────────────────────────
def geocode_city(city):
    if not city or not city.strip():
        return None, None
    try:
        url = "https://nominatim.openstreetmap.org/search?format=json&q=" + requests.utils.quote(city.strip())
        response = requests.get(url, headers={'User-Agent': 'CityProblem/1.0'}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                lat = data[0].get('lat')
                lon = data[0].get('lon')
                if lat and lon:
                    return float(lat), float(lon)
    except Exception as e:
        print(f"Geocoding error for {city}: {e}")
    return None, None

def get_monthly_data(year):
    from collections import defaultdict
    monthly = defaultdict(int)
    for c in get_complaints():
        if c['date'].startswith(str(year)):
            month = int(c['date'].split('-')[1])
            monthly[month] += 1
    return [monthly.get(m, 0) for m in range(1, 13)]

def get_department_perf():
    from collections import defaultdict
    regions = defaultdict(lambda: {'total': 0, 'resolved': 0, 'days': []})
    for c in get_complaints():
        location = c['location']
        region = location
        regions[region]['total'] += 1
        if c['status'] == 'Resolved':
            regions[region]['resolved'] += 1
        # For avg_days, assume current date - date
        try:
            date_obj = datetime.strptime(c['date'], '%Y-%m-%d')
            days = (datetime.now() - date_obj).days
            regions[region]['days'].append(days)
        except:
            pass
    perf = []
    for region, data in regions.items():
        avg_days = sum(data['days']) / len(data['days']) if data['days'] else 0
        status = 'Good' if data['resolved'] / data['total'] > 0.8 else 'Average' if data['resolved'] / data['total'] > 0.6 else 'Needs Attention'
        perf.append({
            'region': region,
            'total': data['total'],
            'resolved': data['resolved'],
            'avg_days': round(avg_days, 1),
            'status': status
        })
    return perf

def get_map_issues():
    from collections import defaultdict
    issues = defaultdict(lambda: {'count': 0, 'types': set(), 'lat': 0, 'lng': 0})
    for c in get_complaints():
        city = c['location']
        issues[city]['count'] += 1
        issues[city]['types'].add(c['type'])
        if 'lat' in c and c['lat'] is not None:
            issues[city]['lat'] = c['lat']
            issues[city]['lng'] = c['lng']
    map_issues = []
    for city, data in issues.items():
        if data['lat'] != 0 and data['lng'] != 0:  # Only include cities with valid coordinates
            density = 'high' if data['count'] > 10 else 'medium' if data['count'] > 5 else 'low'
            map_issues.append({
                'lat': data['lat'],
                'lng': data['lng'],
                'city': city,
                'type': list(data['types'])[0] if data['types'] else 'pothole',
                'density': density,
                'count': data['count']
            })
    return map_issues

def get_dashboard_stats():
    all_complaints = get_complaints()
    total_issues = len(all_complaints)
    resolved = sum(1 for c in all_complaints if c['status'] == 'Resolved')
    pending = total_issues - resolved
    avg_days = 0
    if resolved > 0:
        days_list = []
        for c in all_complaints:
            if c['status'] == 'Resolved':
                try:
                    date_obj = datetime.strptime(c['date'], '%Y-%m-%d')
                    days = (datetime.now() - date_obj).days
                    days_list.append(days)
                except:
                    pass
        avg_days = sum(days_list) / len(days_list) if days_list else 0
    from collections import Counter
    locations = [c['location'] for c in all_complaints]
    most_affected = Counter(locations).most_common(1)[0][0] if locations else 'None'
    active = sum(1 for c in all_complaints if c['status'] != 'Resolved')
    issue_types = {}
    for c in all_complaints:
        t = c['type']
        if t not in issue_types:
            issue_types[t] = {'count': 0, 'resolved': 0}
        issue_types[t]['count'] += 1
        if c['status'] == 'Resolved':
            issue_types[t]['resolved'] += 1
    issue_list = []
    icons = {'Pothole': '🚧', 'Broken Light': '💡', 'Garbage Overflow': '🗑️', 'Electric Fault': '⚡'}
    colors = {'Pothole': '#fff3e0', 'Broken Light': '#e8f0fe', 'Garbage Overflow': '#e8f5e9', 'Electric Fault': '#f3e8ff'}
    for t, data in issue_types.items():
        pct = int(data['resolved'] / data['count'] * 100) if data['count'] > 0 else 0
        issue_list.append({
            'type': t,
            'count': data['count'],
            'pct': pct,
            'icon': icons.get(t, '❓'),
            'color': colors.get(t, '#f0f0f0')
        })
    resolution_rate = int(resolved / total_issues * 100) if total_issues > 0 else 0
    active_complaints = total_issues - resolved
    top_category = max(issue_list, key=lambda x: x['count'])['type'] if issue_list else 'None'
    top_count = max(issue_list, key=lambda x: x['count'])['count'] if issue_list else 0
    return {
        'total_issues': total_issues,
        'resolved': resolved,
        'avg_days': round(avg_days, 1),
        'most_affected': most_affected,
        'active': active,
        'issue_types': issue_list,
        'resolution_rate': resolution_rate,
        'active_complaints': active_complaints,
        'top_category': top_category,
        'top_count': top_count
    }

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/login/demo")
def login_demo():
    session["user"] = {"name": "John Doe", "email": "john@cityproblem.gov", "picture": None, "initials": "JD"}
    return redirect(url_for("dashboard"))

@app.route("/login/google")
def login_google():
    if not OAUTH_AVAILABLE:
        return redirect(url_for("login_demo"))
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    if not OAUTH_AVAILABLE:
        return redirect(url_for("dashboard"))
    token = google.authorize_access_token()
    user_info = token.get("userinfo")
    if user_info:
        name = user_info.get("name", "User")
        initials = "".join([p[0].upper() for p in name.split()[:2]])
        session["user"] = {
            "name": name,
            "email": user_info.get("email"),
            "picture": user_info.get("picture"),
            "initials": initials,
        }
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_dashboard_stats()
    perf = get_department_perf()
    alerts_count = sum(1 for a in get_alerts() if a.get("read") is False)
    return render_template("dashboard.html", user=session["user"], page="dashboard",
                           stats=stats, perf=perf, alerts_count=alerts_count)

@app.route("/complaints")
@login_required
def complaints():
    # Fetch all complaints from MongoDB (or fallback to in-memory list)
    if MONGO_AVAILABLE:
        all_data = list(complaints_col.find({}, {"_id": 0}))
    else:
        all_data = get_complaints()
    alerts_count = sum(1 for a in get_alerts() if a.get("read") is False)
    return render_template("complaints.html", user=session["user"], page="complaints",
                           complaints=all_data, data=all_data, alerts_count=alerts_count)

@app.route("/analytics")
@login_required
def analytics():
    stats = get_dashboard_stats()
    perf = get_department_perf()
    alerts_count = sum(1 for a in get_alerts() if a.get("read") is False)
    return render_template("analytics.html", user=session["user"], page="analytics",
                           stats=stats, perf=perf, alerts_count=alerts_count)

@app.route("/alerts")
@login_required
def alerts():
    all_alerts = get_alerts()
    alerts_count = sum(1 for a in all_alerts if a.get("read") is False)
    return render_template("alerts.html", user=session["user"], page="alerts",
                           alerts=all_alerts, alerts_count=alerts_count)

# ── Complaints CRUD ───────────────────────────────────────────────────────────

@app.route("/complaints/add", methods=["GET", "POST"])
@app.route("/add", methods=["POST"])  # Alias for simplified form submission
@login_required
def add_complaint():
    """Adds a new complaint with optional image upload (ImageKit)."""
    global complaint_counter
    if request.method == "POST":
        print(f"DEBUG: Files received: {request.files}")
        print(f"DEBUG: Form data: {request.form}")
        try:
            # 1. Handle image upload (Optional)
            image = request.files.get("image")
            image_url = None
            file_id = None
            
            if image and image.filename:
                print(f"DEBUG: Processing upload for: {image.filename}")
                try:
                    # Reset pointer just in case
                    image.seek(0)
                    img_bytes = image.read()
                    
                    if img_bytes:
                        # Direct API call with binary data is often more robust 
                        # than base64 strings in some python/server environments
                        ik_response = requests.post(
                            "https://upload.imagekit.io/api/v1/files/upload",
                            auth=(os.getenv("IMAGEKIT_PRIVATE_KEY"), ""),
                            files={
                                "file": (image.filename, img_bytes, image.content_type),
                                "fileName": (None, image.filename),
                                "useUniqueFileName": (None, "true")
                            }
                        )
                        
                        if ik_response.status_code == 200:
                            ik_data = ik_response.json()
                            image_url = ik_data.get("url")
                            file_id = ik_data.get("fileId")
                            print(f"✅ ImageKit Upload Success: {image_url}")
                            flash("Image uploaded successfully!", "success")
                        else:
                            err_msg = ik_response.text
                            print(f"❌ ImageKit API Error: {err_msg}")
                            flash(f"Cloud Upload Failed: {err_msg}", "warning")
                    else:
                        print("⚠️ Upload skipped: File was empty.")
                        flash("Image file was empty.", "warning")

                except Exception as ik_err:
                    print(f"❌ Upload Exception: {ik_err}")
                    flash(f"Upload logic error: {str(ik_err)}", "danger")



            # 2. Location & ID generation
            city = request.form.get("city", "")
            lat, lng = geocode_city(city)
            
            if MONGO_AVAILABLE:
                count = complaints_col.count_documents({})
                cid = f"CMR-{count + 1:03d}"
            else:
                cid = f"CMR-{complaint_counter:03d}"

            # 3. Create document
            new_complaint = {
                "id": cid,
                "type": request.form.get("type"),
                "city": city,
                "location": city,
                "description": request.form.get("description", ""),
                "lat": lat,
                "lng": lng,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "status": "Pending",
                "priority": request.form.get("priority"),
                "image_url": image_url,
                "file_id": file_id
            }

            # 4. Save to DB
            print(f"DEBUG: FINAL DATA TO SAVE: {new_complaint}")
            if MONGO_AVAILABLE:
                complaints_col.insert_one(new_complaint)
            else:
                COMPLAINTS.append(new_complaint)
                complaint_counter += 1
                
            return redirect(url_for("complaints"))
            
        except Exception as e:
            print(f"❌ Critical error in add_complaint: {e}")
            return redirect(url_for("complaints"))
            
    return render_template("add_complaint.html", user=session["user"], page="complaints",
                           alerts_count=sum(1 for a in get_alerts() if a.get("read") is False))

@app.route("/complaints/edit/<complaint_id>", methods=["GET", "POST"])
@login_required
def edit_complaint(complaint_id):
    if MONGO_AVAILABLE:
        complaint = complaints_col.find_one({"id": complaint_id}, {"_id": 0})
    else:
        complaint = next((c for c in COMPLAINTS if c["id"] == complaint_id), None)
    if not complaint:
        return "Complaint not found", 404
    if request.method == "POST":
        try:
            city = request.form["city"]
            lat, lng = geocode_city(city)
            updates = {
                "type": request.form["type"],
                "location": city,
                "description": request.form.get("description", ""),
                "lat": lat,
                "lng": lng,
                "status": request.form["status"],
                "priority": request.form["priority"]
            }
            if MONGO_AVAILABLE:
                complaints_col.update_one({"id": complaint_id}, {"$set": updates})
            else:
                complaint.update(updates)
            return redirect(url_for("complaints"))
        except Exception as e:
            print(f"Error editing complaint: {e}")
            return redirect(url_for("complaints"))
    return render_template("edit_complaint.html", user=session["user"], page="complaints",
                           complaint=complaint, alerts_count=sum(1 for a in get_alerts() if a.get("read") is False))

@app.route("/complaints/resolve/<complaint_id>")
@login_required
def resolve_complaint(complaint_id):
    """Marks a complaint as Resolved and deletes its linked image from ImageKit to save space."""
    global COMPLAINTS
    if MONGO_AVAILABLE:
        # 1. Fetch metadata to get file_id
        complaint = complaints_col.find_one({"id": complaint_id})
        
        # 2. Delete image from ImageKit if it exists
        if complaint and complaint.get("file_id"):
            try:
                imagekit.files.delete(file_id=complaint["file_id"])
            except Exception as e:
                print(f"⚠️ Error deleting image during resolution: {e}")
        
        # 3. Update document in MongoDB
        complaints_col.update_one(
            {"id": complaint_id},
            {"$set": {"status": "Resolved", "image_url": None, "file_id": None}}
        )
    else:
        # In-memory fallback
        for c in COMPLAINTS:
            if c["id"] == complaint_id:
                c["status"] = "Resolved"
                c["image_url"] = None
                c["file_id"] = None
                break
                
    return redirect(url_for("complaints"))

@app.route("/complaints/delete/<complaint_id>", methods=["POST"])
@login_required
def delete_complaint(complaint_id):
    """Deletes complaint from DB and its image from ImageKit."""
    global COMPLAINTS
    if MONGO_AVAILABLE:
        # 1. Fetch metadata to get file_id
        complaint = complaints_col.find_one({"id": complaint_id})
        
        # 2. Delete image from ImageKit if it exists
        if complaint and complaint.get("file_id"):
            try:
                imagekit.files.delete(file_id=complaint["file_id"])
            except Exception as e:
                print(f"⚠️ Error deleting from ImageKit: {e}")
        
        # 3. Delete from MongoDB
        complaints_col.delete_one({"id": complaint_id})
    else:
        # In-memory fallback
        COMPLAINTS = [c for c in COMPLAINTS if c["id"] != complaint_id]
        
    return redirect(url_for("complaints"))

# ── Alerts CRUD ──────────────────────────────────────────────────────────────

@app.route("/alerts/add", methods=["GET", "POST"])
@login_required
def add_alert():
    global alert_counter
    if request.method == "POST":
        if MONGO_AVAILABLE:
            aid = alerts_col.count_documents({}) + 1
        else:
            aid = alert_counter
        new_alert = {
            "id": aid,
            "title": request.form["title"],
            "desc": request.form["desc"],
            "time": "Just now",
            "level": request.form["level"],
            "read": False
        }
        if MONGO_AVAILABLE:
            alerts_col.insert_one({**new_alert})
        else:
            ALERTS.append(new_alert)
            alert_counter += 1
        return redirect(url_for("alerts"))
    return render_template("add_alert.html", user=session["user"], page="alerts",
                           alerts_count=sum(1 for a in get_alerts() if a.get("read") is False))

@app.route("/alerts/edit/<int:alert_id>", methods=["GET", "POST"])
@login_required
def edit_alert(alert_id):
    if MONGO_AVAILABLE:
        alert = alerts_col.find_one({"id": alert_id}, {"_id": 0})
    else:
        alert = next((a for a in ALERTS if a["id"] == alert_id), None)
    if not alert:
        return "Alert not found", 404
    if request.method == "POST":
        updates = {
            "title": request.form["title"],
            "desc": request.form["desc"],
            "level": request.form["level"],
            "read": request.form.get("read") == "on"
        }
        if MONGO_AVAILABLE:
            alerts_col.update_one({"id": alert_id}, {"$set": updates})
        else:
            alert.update(updates)
        return redirect(url_for("alerts"))
    return render_template("edit_alert.html", user=session["user"], page="alerts",
                           alert=alert, alerts_count=sum(1 for a in get_alerts() if a.get("read") is False))

@app.route("/alerts/delete/<int:alert_id>", methods=["POST"])
@login_required
def delete_alert(alert_id):
    global ALERTS
    if MONGO_AVAILABLE:
        alerts_col.delete_one({"id": alert_id})
    else:
        ALERTS = [a for a in ALERTS if a["id"] != alert_id]
    return redirect(url_for("alerts"))

# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/monthly-data")
@login_required
def api_monthly_data():
    year = request.args.get("year", "2024")
    return jsonify(get_monthly_data(int(year)))

@app.route("/api/map-issues")
@login_required
def api_map_issues():
    return jsonify(get_map_issues())

@app.route("/api/complaint", methods=["POST"])
@login_required
def api_add_complaint():
    """API endpoint for frontend FormData submissions."""
    print(f"DEBUG: API Files received: {request.files}")
    print(f"DEBUG: API Form data: {request.form}")
    try:
        # 1. Handle image upload (Optional)
        image = request.files.get("image")
        image_url = None
        file_id = None
        
        if image and image.filename:
            print(f"DEBUG: API processing upload for: {image.filename}")
            try:
                image.seek(0)
                img_bytes = image.read()
                if img_bytes:
                    # Direct Binary Upload
                    ik_response = requests.post(
                        "https://upload.imagekit.io/api/v1/files/upload",
                        auth=(os.getenv("IMAGEKIT_PRIVATE_KEY"), ""),
                        files={
                            "file": (image.filename, img_bytes, image.content_type),
                            "fileName": (None, image.filename),
                            "useUniqueFileName": (None, "true")
                        }
                    )
                    
                    if ik_response.status_code == 200:
                        ik_data = ik_response.json()
                        image_url = ik_data.get("url")
                        file_id = ik_data.get("fileId")
                        print(f"✅ API ImageKit Success: {image_url}")
                    else:
                        print(f"❌ API ImageKit Error: {ik_response.text}")
                        return jsonify({"success": False, "error": ik_response.text}), 400
                else:
                    print("⚠️ API Image file empty.")
            except Exception as ik_err:
                print(f"⚠️ API Exception: {ik_err}")
                return jsonify({"success": False, "error": str(ik_err)}), 400

        # 2. Form data
        comp_type = request.form.get("type", "Pothole")
        desc = request.form.get("description", "")
        city = request.form.get("city", "New York")  # Default or from form
        
        lat, lng = geocode_city(city)
        if MONGO_AVAILABLE:
            cid = f"CMR-{complaints_col.count_documents({}) + 1:03d}"
        else:
            global complaint_counter
            cid = f"CMR-{complaint_counter:03d}"

        # 3. Create document (similar to ...req.body in Node)
        data = {
            **request.form.to_dict(),
            "id": cid,
            "city": city,
            "location": city,
            "lat": lat,
            "lng": lng,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": "Pending",
            "image_url": image_url,
            "file_id": file_id
        }

        # 4. Save to DB
        print(f"DEBUG: FINAL API DATA TO SAVE: {data}")
        if MONGO_AVAILABLE:
            complaints_col.insert_one(data)
        else:
            COMPLAINTS.append(data)
            complaint_counter += 1

        # Use JSON response structure matching your Node.js final structure
        if "_id" in data:
            data.pop("_id")  # MongoDB internal IDs aren't JSON serializable directly
            
        return jsonify({"success": True, "data": data}), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/alerts/mark-read/<int:alert_id>", methods=["POST"])
@login_required
def mark_alert_read(alert_id):
    if MONGO_AVAILABLE:
        alerts_col.update_one({"id": alert_id}, {"$set": {"read": True}})
    else:
        for a in ALERTS:
            if a["id"] == alert_id:
                a["read"] = True
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
