import os, json, secrets, re, time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash


db = SQLAlchemy()

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
ADMIN_PASSWORD_RECOVERY_MIGRATION = "20260905_02_admin_password_recovery"
ADMIN_LOGIN_ALIAS = "admin@aplsai.it"
_login_attempts = {}


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    production = os.environ.get("FLASK_ENV") == "production"

    secret_key = os.environ.get("SECRET_KEY")
    if production and not secret_key:
        raise RuntimeError("SECRET_KEY obbligatoria in produzione")
    app.config["SECRET_KEY"] = secret_key or secrets.token_hex(32)

    db_url = os.environ.get("DATABASE_URL", "sqlite:///aplsai.db")
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

    app.config["SESSION_COOKIE_NAME"] = "aplsai_session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = production
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_admin()

    @app.before_request
    def security_gate():
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not request.is_json:
                return jsonify(error="Richiesta non valida."), 415

            origin = request.headers.get("Origin")
            referer = request.headers.get("Referer")
            source = origin or referer
            if source:
                try:
                    parsed = urlparse(source)
                    source_host = parsed.netloc.lower()
                    if source_host and source_host != request.host.lower():
                        return jsonify(error="Origine richiesta non autorizzata."), 403
                except Exception:
                    return jsonify(error="Origine richiesta non valida."), 403

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https://images.unsplash.com; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="online")

    @app.post("/api/register")
    def register():
        d = request.get_json(silent=True) or {}
        name = clean_text(d.get("name"), 160)
        email = clean_email(d.get("email"))
        phone = clean_text(d.get("phone"), 40)
        password = d.get("password") or ""
        profile = d.get("profile") or {}

        if not name or not valid_email(email) or not valid_phone(phone):
            return jsonify(error="Completa correttamente nome, email e WhatsApp."), 400
        if not strong_password(password):
            return jsonify(error="La password deve avere almeno 10 caratteri, con lettere e numeri."), 400
        if not validate_profile(profile):
            return jsonify(error="Profilo di ricerca non valido o incompleto."), 400
        if User.query.filter_by(email=email).first():
            return jsonify(error="Email già registrata."), 409

        u = User(
            role="client", name=name, email=email, phone=phone,
            password_hash=generate_password_hash(password, method="scrypt")
        )
        db.session.add(u)
        db.session.flush()

        c = ClientProfile(
            user_id=u.id,
            profile_json=json.dumps(profile, ensure_ascii=False),
            status="Ricerca attiva",
            last_contact_at=utcnow()
        )
        db.session.add(c)
        db.session.add(Update(client_id=u.id, message="Ricerca APLSAI avviata."))
        db.session.commit()

        establish_session(u.id)
        return jsonify(client=client_obj(u.id)), 201

    @app.post("/api/client/login")
    def client_login():
        d = request.get_json(silent=True) or {}
        email = clean_email(d.get("email"))
        password = d.get("password") or ""
        key = login_key("client", email)
        if login_blocked(key):
            return jsonify(error="Troppi tentativi. Riprova tra qualche minuto."), 429

        u = User.query.filter_by(email=email, role="client").first()
        if not u or not check_password_hash(u.password_hash, password):
            register_login_failure(key)
            return jsonify(error="Email o password errati."), 401

        clear_login_failures(key)
        establish_session(u.id)
        return jsonify(client=client_obj(u.id))

    @app.post("/api/staff/login")
    def staff_login():
        d = request.get_json(silent=True) or {}
        submitted_email = clean_email(d.get("email"))
        email = (
            clean_email(os.environ.get("ADMIN_EMAIL"))
            if submitted_email == ADMIN_LOGIN_ALIAS
            else submitted_email
        )
        password = d.get("password") or ""
        # Keep the alias on its own rate-limit key so an administrator who was
        # blocked after mistyping the long email can still recover access.
        key = login_key("staff", submitted_email)
        if login_blocked(key):
            return jsonify(error="Troppi tentativi. Riprova tra qualche minuto."), 429

        u = User.query.filter_by(email=email, role="staff").first()
        if not u or not check_password_hash(u.password_hash, password):
            register_login_failure(key)
            return jsonify(error="Credenziali staff errate."), 401

        clear_login_failures(key)
        establish_session(u.id)
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/client/me")
    def client_me():
        u = require_role("client")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/strategy")
    def client_strategy():
        u = require_role("client")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        d = request.get_json(silent=True) or {}
        strategy = clean_text(d.get("strategy"), 100)
        allowed = {"Priorità Zona", "Priorità Casa", "Miglior Equilibrio"}
        if strategy not in allowed:
            return jsonify(error="Strategia non valida."), 400
        cp = ClientProfile.query.filter_by(user_id=u.id).first()
        cp.preferred_strategy = strategy
        cp.last_contact_at = utcnow()
        db.session.add(Update(client_id=u.id, message=f"Strategia scelta: {strategy}."))
        db.session.commit()
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/toggle-pause")
    def client_pause():
        u = require_role("client")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        cp = ClientProfile.query.filter_by(user_id=u.id).first()
        cp.status = "Ricerca attiva" if cp.status == "In pausa" else "In pausa"
        db.session.add(Update(client_id=u.id, message=f"Ricerca: {cp.status}."))
        db.session.commit()
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/referrals")
    def referral_create():
        u = require_role("client")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        d = request.get_json(silent=True) or {}
        friend = clean_email(d.get("friend_email"))
        if not valid_email(friend):
            return jsonify(error="Email amico non valida."), 400
        if friend == u.email:
            return jsonify(error="Non puoi invitare il tuo stesso indirizzo email."), 400
        r = Referral(
            owner_id=u.id,
            friend_email=friend,
            code="APL-" + secrets.token_hex(3).upper(),
            status="Invitato",
            reward="Da definire"
        )
        db.session.add(r)
        db.session.commit()
        return jsonify(client=client_obj(u.id)), 201

    @app.get("/api/staff/dashboard")
    def staff_dashboard():
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        clients = [client_obj(x.user_id) for x in ClientProfile.query.all()]
        return jsonify(
            clients=clients,
            properties=[p.to_dict() for p in Property.query.order_by(Property.created_at.desc()).all()],
            deals=[d.to_dict() for d in Deal.query.order_by(Deal.updated_at.desc()).all()],
            referrals=[r.to_dict() for r in Referral.query.order_by(Referral.created_at.desc()).all()],
            documents=[d.to_dict() for d in Document.query.order_by(Document.created_at.desc()).all()]
        )

    @app.post("/api/staff/properties")
    def property_create():
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        d = request.get_json(silent=True) or {}
        ref = clean_text(d.get("ref"), 120)
        zone = clean_text(d.get("zone"), 200)
        state = clean_text(d.get("state"), 100)
        source = clean_text(d.get("source") or "Staff", 100)
        try:
            price = float(d.get("price"))
            sqm = float(d.get("sqm"))
            beds = int(d.get("beds") or 0)
            baths = int(d.get("baths") or 0)
        except (TypeError, ValueError):
            return jsonify(error="Dati immobile non validi."), 400
        if not ref or not zone or price <= 0 or sqm <= 0 or not (0 <= beds <= 30) or not (0 <= baths <= 30):
            return jsonify(error="Dati immobile incompleti o non validi."), 400
        p = Property(ref=ref, zone=zone, price=price, sqm=sqm, beds=beds, baths=baths, state=state, source=source)
        db.session.add(p)
        db.session.commit()
        return jsonify(ok=True, id=p.id), 201

    @app.get("/api/staff/match/client/<int:client_id>")
    def match_client(client_id):
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        c = client_obj(client_id)
        if not c:
            return jsonify(error="Cliente non trovato."), 404
        rows = []
        for p in Property.query.all():
            sc, reason = match_score(c, p.to_dict())
            rows.append({"property": p.to_dict(), "score": sc, "reason": reason})
        rows.sort(key=lambda x: x["score"], reverse=True)
        return jsonify(client=c, results=rows)

    @app.get("/api/staff/match/property/<int:property_id>")
    def match_property(property_id):
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        p = db.session.get(Property, property_id)
        if not p:
            return jsonify(error="Immobile non trovato."), 404
        rows = []
        for cp in ClientProfile.query.all():
            c = client_obj(cp.user_id)
            sc, reason = match_score(c, p.to_dict())
            rows.append({"client": c, "score": sc, "reason": reason})
        rows.sort(key=lambda x: x["score"], reverse=True)
        return jsonify(property=p.to_dict(), results=rows)

    @app.post("/api/staff/proposals")
    def proposal_create():
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        d = request.get_json(silent=True) or {}
        try:
            client_id = int(d.get("client_id"))
            property_id = int(d.get("property_id"))
        except (TypeError, ValueError):
            return jsonify(error="Dati proposta non validi."), 400
        cp = ClientProfile.query.filter_by(user_id=client_id).first()
        prop = db.session.get(Property, property_id)
        if not cp or not prop:
            return jsonify(error="Cliente o immobile non trovato."), 404
        ref = clean_text(d.get("ref") or prop.ref, 120)
        deal = Deal(client_id=client_id, property_id=property_id, ref=ref, stage="Proposta")
        cp.proposal_count = (cp.proposal_count or 0) + 1
        cp.last_proposal_at = utcnow()
        db.session.add(deal)
        db.session.add(Update(client_id=cp.user_id, message=f"Nuova opportunità proposta: {deal.ref}."))
        db.session.commit()
        return jsonify(ok=True, id=deal.id), 201

    @app.post("/api/staff/documents")
    def document_create():
        u = require_role("staff")
        if not u:
            return jsonify(error="Non autorizzato."), 401
        d = request.get_json(silent=True) or {}
        try:
            client_id = int(d.get("client_id"))
        except (TypeError, ValueError):
            return jsonify(error="Cliente non valido."), 400
        if not ClientProfile.query.filter_by(user_id=client_id).first():
            return jsonify(error="Cliente non trovato."), 404
        title = clean_text(d.get("title"), 255)
        url = clean_text(d.get("url"), 1000)
        if not title:
            return jsonify(error="Titolo documento obbligatorio."), 400
        if url and not valid_http_url(url):
            return jsonify(error="Link documento non valido."), 400
        doc = Document(client_id=client_id, title=title, url=url)
        db.session.add(doc)
        db.session.add(Update(client_id=doc.client_id, message=f"Nuovo documento condiviso: {doc.title}."))
        db.session.commit()
        return jsonify(ok=True, id=doc.id), 201

    return app


def utcnow():
    return datetime.now(timezone.utc)


def clean_text(value, max_len):
    if value is None:
        return ""
    value = str(value).strip()
    return value[:max_len]


def clean_email(value):
    return clean_text(value, 255).lower()


def valid_email(value):
    return bool(value and EMAIL_RE.match(value))


def valid_phone(value):
    if not value or len(value) < 6 or len(value) > 40:
        return False
    return bool(re.fullmatch(r"[0-9+() .\-/]+", value))


def strong_password(password):
    return (
        isinstance(password, str)
        and 10 <= len(password) <= 128
        and any(c.isalpha() for c in password)
        and any(c.isdigit() for c in password)
    )


def valid_http_url(value):
    try:
        p = urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def validate_profile(profile):
    if not isinstance(profile, dict):
        return False
    try:
        if len(json.dumps(profile, ensure_ascii=False)) > 20000:
            return False
        zone = profile.get("zone") or {}
        budget = profile.get("budget") or {}
        spaces = profile.get("spaces") or {}
        main = clean_text(zone.get("main"), 200)
        km = float(zone.get("km"))
        ideal = float(budget.get("ideal"))
        maximum = float(budget.get("max"))
        flex = float(budget.get("flex"))
        sqm = float(spaces.get("sqm"))
        beds = int(spaces.get("beds"))
        baths = int(spaces.get("baths"))
        timing = clean_text(profile.get("timing"), 80)
        style = clean_text(profile.get("style"), 100)
        must = profile.get("must") or []
        house_types = profile.get("houseTypes") or []
        purchase = profile.get("purchase") or []
        if not main or not timing or not style:
            return False
        if not (1 <= km <= 200 and 1000 <= ideal <= maximum <= 100000000 and 0 <= flex <= 100):
            return False
        if not (10 <= sqm <= 5000 and 0 <= beds <= 30 and 0 <= baths <= 30):
            return False
        if not all(isinstance(x, str) and 0 < len(x) <= 100 for x in must[:30]):
            return False
        if not house_types or not all(isinstance(x, str) and 0 < len(x) <= 100 for x in house_types[:30]):
            return False
        if not purchase or not all(isinstance(x, str) and 0 < len(x) <= 100 for x in purchase[:30]):
            return False
        return True
    except (TypeError, ValueError):
        return False


def login_key(role, email):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    return f"{role}:{ip}:{email or '-'}"


def _recent_attempts(key):
    now = time.time()
    attempts = [t for t in _login_attempts.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    if attempts:
        _login_attempts[key] = attempts
    else:
        _login_attempts.pop(key, None)
    return attempts


def login_blocked(key):
    return len(_recent_attempts(key)) >= LOGIN_MAX_ATTEMPTS


def register_login_failure(key):
    attempts = _recent_attempts(key)
    attempts.append(time.time())
    _login_attempts[key] = attempts[-LOGIN_MAX_ATTEMPTS:]


def clear_login_failures(key):
    _login_attempts.pop(key, None)


def establish_session(uid):
    session.clear()
    session["uid"] = uid
    session["nonce"] = secrets.token_urlsafe(16)
    session.permanent = True


def require_role(role):
    uid = session.get("uid")
    if not uid:
        return None
    u = db.session.get(User, uid)
    if not u or u.role != role:
        session.clear()
        return None
    return u


def seed_admin():
    email = clean_email(os.environ.get("ADMIN_EMAIL"))
    password = os.environ.get("ADMIN_PASSWORD") or ""

    legacy = User.query.filter_by(email="admin@aplsai.local", role="staff").first()
    if legacy and check_password_hash(legacy.password_hash, "Admin123!"):
        db.session.delete(legacy)
        db.session.commit()

    if not email and not password:
        return
    if not valid_email(email) or not strong_password(password):
        raise RuntimeError("ADMIN_EMAIL/ADMIN_PASSWORD non validi: usa email valida e password forte")

    existing = User.query.filter_by(email=email).first()
    if existing:
        if existing.role != "staff":
            raise RuntimeError("ADMIN_EMAIL già usata da un utente non staff")
        _apply_one_time_admin_password_recovery(existing, password)
        return

    existing = User(
        role="staff", name="APLSAI Admin", email=email, phone="",
        password_hash=generate_password_hash(password, method="scrypt")
    )
    db.session.add(existing)
    db.session.flush()
    _apply_one_time_admin_password_recovery(existing, password)


def _apply_one_time_admin_password_recovery(admin, password):
    """Restore the configured admin password once, then preserve later changes."""
    db.session.execute(text(
        "CREATE TABLE IF NOT EXISTS aplsai_schema_migration ("
        "id VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
    ))
    applied = db.session.execute(
        text("SELECT 1 FROM aplsai_schema_migration WHERE id=:id"),
        {"id": ADMIN_PASSWORD_RECOVERY_MIGRATION},
    ).first()
    if not applied:
        admin.password_hash = generate_password_hash(password, method="scrypt")
        db.session.execute(
            text(
                "INSERT INTO aplsai_schema_migration (id, applied_at) "
                "VALUES (:id, :applied_at)"
            ),
            {
                "id": ADMIN_PASSWORD_RECOVERY_MIGRATION,
                "applied_at": utcnow(),
            },
        )
    db.session.commit()


def client_obj(uid):
    u = db.session.get(User, uid)
    cp = ClientProfile.query.filter_by(user_id=uid).first()
    if not u or not cp:
        return None
    try:
        p = json.loads(cp.profile_json)
    except Exception:
        p = {}
    created = u.created_at
    if created is None:
        days = 0
    else:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        else:
            created = created.astimezone(timezone.utc)
        days = max(0, (utcnow() - created).days)
    return {
        "id": u.id, "name": u.name, "email": u.email, "phone": u.phone,
        "status": cp.status, "preferred_strategy": cp.preferred_strategy,
        "proposal_count": cp.proposal_count or 0, "days_aplsai": days,
        "updates": [x.to_dict() for x in Update.query.filter_by(client_id=uid).order_by(Update.created_at.desc()).all()],
        "documents": [x.to_dict() for x in Document.query.filter_by(client_id=uid).order_by(Document.created_at.desc()).all()],
        "referrals": [x.to_dict() for x in Referral.query.filter_by(owner_id=uid).order_by(Referral.created_at.desc()).all()],
        **p
    }


def match_score(c, p):
    s = 0
    why = []
    if p["price"] <= c["budget"]["max"]:
        s += 30
        why.append("budget compatibile")
    elif p["price"] <= c["budget"]["max"] * (1 + (c["budget"].get("flex") or 0) / 100):
        s += 22
        why.append("budget con flessibilità")
    if p["zone"].lower() in c["zone"]["main"].lower() or c["zone"]["main"].lower() in p["zone"].lower():
        s += 25
        why.append("zona coerente")
    else:
        s += 10
        why.append("zona da verificare")
    if p["sqm"] >= c["spaces"]["sqm"]:
        s += 20
        why.append("metratura ok")
    if (p["beds"] or 0) >= c["spaces"]["beds"]:
        s += 10
    if (p["baths"] or 0) >= c["spaces"]["baths"]:
        s += 5
    if p["state"] in c.get("purchase", []):
        s += 10
        why.append("stato coerente")
    return min(100, s), ", ".join(why)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(80), default="")
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class ClientProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False, index=True)
    profile_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default="Ricerca attiva")
    preferred_strategy = db.Column(db.String(100))
    last_contact_at = db.Column(db.DateTime(timezone=True))
    last_proposal_at = db.Column(db.DateTime(timezone=True))
    proposal_count = db.Column(db.Integer, default=0)


class Update(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    message = db.Column(db.Text, nullable=False)

    def to_dict(self):
        return {"id": self.id, "client_id": self.client_id, "created_at": self.created_at.isoformat(), "message": self.message}


class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ref = db.Column(db.String(120), nullable=False)
    zone = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    sqm = db.Column(db.Float, nullable=False)
    beds = db.Column(db.Integer, default=0)
    baths = db.Column(db.Integer, default=0)
    state = db.Column(db.String(100), default="")
    source = db.Column(db.String(100), default="Staff")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "ref": self.ref, "zone": self.zone, "price": self.price, "sqm": self.sqm, "beds": self.beds, "baths": self.baths, "state": self.state, "source": self.source, "created_at": self.created_at.isoformat()}


class Deal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False)
    ref = db.Column(db.String(120), default="")
    stage = db.Column(db.String(80), default="Proposta")
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "client_id": self.client_id, "property_id": self.property_id, "ref": self.ref, "stage": self.stage, "updated_at": self.updated_at.isoformat()}


class Referral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    friend_email = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(80), default="Invitato")
    reward = db.Column(db.String(120), default="Da definire")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "owner_id": self.owner_id, "friend_email": self.friend_email, "code": self.code, "status": self.status, "reward": self.reward, "created_at": self.created_at.isoformat()}


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    url = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    def to_dict(self):
        return {"id": self.id, "client_id": self.client_id, "title": self.title, "url": self.url, "created_at": self.created_at.isoformat()}
