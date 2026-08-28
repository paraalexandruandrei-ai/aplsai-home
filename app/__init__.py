
import os, json, secrets
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db=SQLAlchemy()

def create_app():
    app=Flask(__name__,template_folder="templates",static_folder="static")
    app.config["SECRET_KEY"]=os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    db_url=os.environ.get("DATABASE_URL","sqlite:///aplsai.db")
    if db_url.startswith("postgres://"):
        db_url="postgresql://"+db_url[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"]=db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    app.config["SESSION_COOKIE_HTTPONLY"]=True
    app.config["SESSION_COOKIE_SAMESITE"]="Lax"
    app.config["SESSION_COOKIE_SECURE"]=os.environ.get("FLASK_ENV")=="production"

    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_admin()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(status="online")

    @app.post("/api/register")
    def register():
        d=request.get_json(force=True)
        name=(d.get("name") or "").strip()
        email=(d.get("email") or "").strip().lower()
        phone=(d.get("phone") or "").strip()
        password=d.get("password") or ""
        profile=d.get("profile") or {}

        if not name or not email or not phone or len(password)<8:
            return jsonify(error="Completa i dati obbligatori."),400
        if User.query.filter_by(email=email).first():
            return jsonify(error="Email già registrata."),409

        u=User(
            role="client",name=name,email=email,phone=phone,
            password_hash=generate_password_hash(password)
        )
        db.session.add(u);db.session.flush()

        c=ClientProfile(
            user_id=u.id,
            profile_json=json.dumps(profile,ensure_ascii=False),
            status="Ricerca attiva",
            last_contact_at=utcnow()
        )
        db.session.add(c)
        db.session.add(Update(client_id=u.id,message="Ricerca APLSAI avviata."))
        db.session.commit()

        session["uid"]=u.id
        return jsonify(client=client_obj(u.id)),201

    @app.post("/api/client/login")
    def client_login():
        d=request.get_json(force=True)
        u=User.query.filter_by(email=(d.get("email") or "").strip().lower(),role="client").first()
        if not u or not check_password_hash(u.password_hash,d.get("password") or ""):
            return jsonify(error="Email o password errati."),401
        session["uid"]=u.id
        return jsonify(client=client_obj(u.id))

    @app.post("/api/staff/login")
    def staff_login():
        d=request.get_json(force=True)
        u=User.query.filter_by(email=(d.get("email") or "").strip().lower(),role="staff").first()
        if not u or not check_password_hash(u.password_hash,d.get("password") or ""):
            return jsonify(error="Credenziali staff errate."),401
        session["uid"]=u.id
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/client/me")
    def client_me():
        u=require_role("client")
        if not u:return jsonify(error="Non autorizzato."),401
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/strategy")
    def client_strategy():
        u=require_role("client")
        if not u:return jsonify(error="Non autorizzato."),401
        strategy=(request.get_json(force=True).get("strategy") or "").strip()
        cp=ClientProfile.query.filter_by(user_id=u.id).first()
        cp.preferred_strategy=strategy
        cp.last_contact_at=utcnow()
        db.session.add(Update(client_id=u.id,message=f"Strategia scelta: {strategy}."))
        db.session.commit()
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/toggle-pause")
    def client_pause():
        u=require_role("client")
        if not u:return jsonify(error="Non autorizzato."),401
        cp=ClientProfile.query.filter_by(user_id=u.id).first()
        cp.status="Ricerca attiva" if cp.status=="In pausa" else "In pausa"
        db.session.add(Update(client_id=u.id,message=f"Ricerca: {cp.status}."))
        db.session.commit()
        return jsonify(client=client_obj(u.id))

    @app.post("/api/client/referrals")
    def referral_create():
        u=require_role("client")
        if not u:return jsonify(error="Non autorizzato."),401
        friend=(request.get_json(force=True).get("friend_email") or "").strip().lower()
        if not friend:return jsonify(error="Email amico mancante."),400
        r=Referral(
            owner_id=u.id,
            friend_email=friend,
            code="APL-"+secrets.token_hex(3).upper(),
            status="Invitato",
            reward="Da definire"
        )
        db.session.add(r);db.session.commit()
        return jsonify(client=client_obj(u.id)),201

    @app.get("/api/staff/dashboard")
    def staff_dashboard():
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        clients=[client_obj(x.user_id) for x in ClientProfile.query.all()]
        return jsonify(
            clients=clients,
            properties=[p.to_dict() for p in Property.query.order_by(Property.created_at.desc()).all()],
            deals=[d.to_dict() for d in Deal.query.order_by(Deal.updated_at.desc()).all()],
            referrals=[r.to_dict() for r in Referral.query.order_by(Referral.created_at.desc()).all()],
            documents=[d.to_dict() for d in Document.query.order_by(Document.created_at.desc()).all()]
        )

    @app.post("/api/staff/properties")
    def property_create():
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        d=request.get_json(force=True)
        if not all(d.get(k) for k in ("ref","zone","price","sqm")):
            return jsonify(error="Dati immobile incompleti."),400
        p=Property(
            ref=d["ref"],zone=d["zone"],price=float(d["price"]),sqm=float(d["sqm"]),
            beds=int(d.get("beds") or 0),baths=int(d.get("baths") or 0),
            state=d.get("state") or "",source=d.get("source") or "Staff"
        )
        db.session.add(p);db.session.commit()
        return jsonify(ok=True,id=p.id),201

    @app.get("/api/staff/match/client/<int:client_id>")
    def match_client(client_id):
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        c=client_obj(client_id)
        if not c:return jsonify(error="Cliente non trovato."),404
        rows=[]
        for p in Property.query.all():
            sc,reason=match_score(c,p.to_dict())
            rows.append({"property":p.to_dict(),"score":sc,"reason":reason})
        rows.sort(key=lambda x:x["score"],reverse=True)
        return jsonify(client=c,results=rows)

    @app.get("/api/staff/match/property/<int:property_id>")
    def match_property(property_id):
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        p=Property.query.get(property_id)
        if not p:return jsonify(error="Immobile non trovato."),404
        rows=[]
        for cp in ClientProfile.query.all():
            c=client_obj(cp.user_id)
            sc,reason=match_score(c,p.to_dict())
            rows.append({"client":c,"score":sc,"reason":reason})
        rows.sort(key=lambda x:x["score"],reverse=True)
        return jsonify(property=p.to_dict(),results=rows)

    @app.post("/api/staff/proposals")
    def proposal_create():
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        d=request.get_json(force=True)
        cp=ClientProfile.query.filter_by(user_id=d.get("client_id")).first()
        if not cp:return jsonify(error="Cliente non trovato."),404
        deal=Deal(
            client_id=int(d["client_id"]),
            property_id=int(d["property_id"]),
            ref=d.get("ref") or "",
            stage="Proposta"
        )
        cp.proposal_count=(cp.proposal_count or 0)+1
        cp.last_proposal_at=utcnow()
        db.session.add(deal)
        db.session.add(Update(client_id=cp.user_id,message=f"Nuova opportunità proposta: {deal.ref}."))
        db.session.commit()
        return jsonify(ok=True,id=deal.id),201

    @app.post("/api/staff/documents")
    def document_create():
        u=require_role("staff")
        if not u:return jsonify(error="Non autorizzato."),401
        d=request.get_json(force=True)
        if not d.get("client_id") or not (d.get("title") or "").strip():
            return jsonify(error="Dati documento incompleti."),400
        doc=Document(
            client_id=int(d["client_id"]),
            title=d["title"].strip(),
            url=(d.get("url") or "").strip()
        )
        db.session.add(doc)
        db.session.add(Update(client_id=doc.client_id,message=f"Nuovo documento condiviso: {doc.title}."))
        db.session.commit()
        return jsonify(ok=True,id=doc.id),201

    return app

def utcnow():
    return datetime.now(timezone.utc)

def require_role(role):
    uid=session.get("uid")
    if not uid:return None
    u=db.session.get(User,uid)
    return u if u and u.role==role else None

def seed_admin():
    email=os.environ.get("ADMIN_EMAIL","admin@aplsai.local").strip().lower()
    password=os.environ.get("ADMIN_PASSWORD","Admin123!")
    if not User.query.filter_by(email=email).first():
        db.session.add(User(
            role="staff",name="APLSAI Admin",email=email,phone="",
            password_hash=generate_password_hash(password)
        ))
        db.session.commit()

def client_obj(uid):
    u=db.session.get(User,uid)
    cp=ClientProfile.query.filter_by(user_id=uid).first()
    if not u or not cp:return None
    p=json.loads(cp.profile_json)
    created=u.created_at
    if created is None:
        days=0
    else:
        if created.tzinfo is None:
            created=created.replace(tzinfo=timezone.utc)
        else:
            created=created.astimezone(timezone.utc)
        days=max(0,(utcnow()-created).days)
    return {
        "id":u.id,"name":u.name,"email":u.email,"phone":u.phone,
        "status":cp.status,"preferred_strategy":cp.preferred_strategy,
        "proposal_count":cp.proposal_count or 0,"days_aplsai":days,
        "updates":[x.to_dict() for x in Update.query.filter_by(client_id=uid).order_by(Update.created_at.desc()).all()],
        "documents":[x.to_dict() for x in Document.query.filter_by(client_id=uid).order_by(Document.created_at.desc()).all()],
        "referrals":[x.to_dict() for x in Referral.query.filter_by(owner_id=uid).order_by(Referral.created_at.desc()).all()],
        **p
    }

def match_score(c,p):
    s=0;why=[]
    if p["price"]<=c["budget"]["max"]:
        s+=30;why.append("budget compatibile")
    elif p["price"]<=c["budget"]["max"]*(1+(c["budget"].get("flex") or 0)/100):
        s+=22;why.append("budget con flessibilità")
    if p["zone"].lower() in c["zone"]["main"].lower() or c["zone"]["main"].lower() in p["zone"].lower():
        s+=25;why.append("zona coerente")
    else:
        s+=10;why.append("zona da verificare")
    if p["sqm"]>=c["spaces"]["sqm"]:
        s+=20;why.append("metratura ok")
    if (p["beds"] or 0)>=c["spaces"]["beds"]:s+=10
    if (p["baths"] or 0)>=c["spaces"]["baths"]:s+=5
    if p["state"] in c.get("purchase",[]):
        s+=10;why.append("stato coerente")
    return min(100,s),", ".join(why)

class User(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    role=db.Column(db.String(20),nullable=False)
    name=db.Column(db.String(160),nullable=False)
    email=db.Column(db.String(255),unique=True,nullable=False,index=True)
    phone=db.Column(db.String(80),default="")
    password_hash=db.Column(db.String(255),nullable=False)
    created_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)

class ClientProfile(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey("user.id"),unique=True,nullable=False,index=True)
    profile_json=db.Column(db.Text,nullable=False)
    status=db.Column(db.String(50),default="Ricerca attiva")
    preferred_strategy=db.Column(db.String(100))
    last_contact_at=db.Column(db.DateTime(timezone=True))
    last_proposal_at=db.Column(db.DateTime(timezone=True))
    proposal_count=db.Column(db.Integer,default=0)

class Update(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    client_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False,index=True)
    created_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)
    message=db.Column(db.Text,nullable=False)
    def to_dict(self):
        return {"id":self.id,"client_id":self.client_id,"created_at":self.created_at.isoformat(),"message":self.message}

class Property(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    ref=db.Column(db.String(120),nullable=False)
    zone=db.Column(db.String(200),nullable=False)
    price=db.Column(db.Float,nullable=False)
    sqm=db.Column(db.Float,nullable=False)
    beds=db.Column(db.Integer,default=0)
    baths=db.Column(db.Integer,default=0)
    state=db.Column(db.String(100),default="")
    source=db.Column(db.String(100),default="Staff")
    created_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)
    def to_dict(self):
        return {"id":self.id,"ref":self.ref,"zone":self.zone,"price":self.price,"sqm":self.sqm,"beds":self.beds,"baths":self.baths,"state":self.state,"source":self.source,"created_at":self.created_at.isoformat()}

class Deal(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    client_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    property_id=db.Column(db.Integer,db.ForeignKey("property.id"),nullable=False)
    ref=db.Column(db.String(120),default="")
    stage=db.Column(db.String(80),default="Proposta")
    updated_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)
    def to_dict(self):
        return {"id":self.id,"client_id":self.client_id,"property_id":self.property_id,"ref":self.ref,"stage":self.stage,"updated_at":self.updated_at.isoformat()}

class Referral(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    owner_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    friend_email=db.Column(db.String(255),nullable=False)
    code=db.Column(db.String(50),nullable=False)
    status=db.Column(db.String(80),default="Invitato")
    reward=db.Column(db.String(120),default="Da definire")
    created_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)
    def to_dict(self):
        return {"id":self.id,"owner_id":self.owner_id,"friend_email":self.friend_email,"code":self.code,"status":self.status,"reward":self.reward,"created_at":self.created_at.isoformat()}

class Document(db.Model):
    id=db.Column(db.Integer,primary_key=True)
    client_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False)
    title=db.Column(db.String(255),nullable=False)
    url=db.Column(db.Text,default="")
    created_at=db.Column(db.DateTime(timezone=True),default=utcnow,nullable=False)
    def to_dict(self):
        return {"id":self.id,"client_id":self.client_id,"title":self.title,"url":self.url,"created_at":self.created_at.isoformat()}
