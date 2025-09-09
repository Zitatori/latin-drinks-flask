from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import json, os, random, pathlib, unicodedata, re

BASE_DIR = pathlib.Path(__file__).parent
DB_PATH = BASE_DIR / "drinks.db"
SEED_PATH = BASE_DIR / "seed_data.json"

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "latin-drinks-demo-secret"  # ローカル用（必要なら変更）
db = SQLAlchemy(app)

class Drink(db.Model):
    id = db.Column(db.String, primary_key=True)
    name_es = db.Column(db.String, nullable=False)
    name_en = db.Column(db.String)              # ← 使わないが互換のため残す
    origin_country = db.Column(db.String, nullable=False)
    category = db.Column(db.String, nullable=False)  # tradition|alcohol|coffee|soft
    abv = db.Column(db.Float, nullable=True)
    serve_temp = db.Column(db.String, nullable=True)
    scene = db.Column(db.String, nullable=True)      # ← 使わないが互換のため残す
    fun_fact_es = db.Column(db.String, nullable=True)
    image_url = db.Column(db.String, nullable=True)

def init_db():
    """初回起動時にDB作成＋シード投入"""
    if not DB_PATH.exists():
        db.create_all()
        with open(SEED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            db.session.add(Drink(**d))
        db.session.commit()

@app.before_request
def ensure_db():
    if not DB_PATH.exists():
        init_db()

CATEGORIES = ["tradition", "alcohol", "coffee", "soft"]

def slugify(text: str) -> str:
    """スペイン語のアクセント除去→小文字→英数字とハイフンだけに"""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9\s_-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    return text or "drink"

def unique_id_from(name_es: str) -> str:
    base = slugify(name_es)
    candidate = base
    i = 2
    while Drink.query.get(candidate):
        candidate = f"{base}-{i}"
        i += 1
    return candidate

@app.route("/")
def home():
    count = db.session.query(func.count(Drink.id)).scalar()
    if count == 0:
        return render_template("empty.html")
    offset = random.randrange(count)
    drink = Drink.query.offset(offset).first()
    return render_template("index.html", drink=drink, categories=CATEGORIES)

@app.route("/drinks")
def drinks():
    q = (request.args.get("q") or "").strip()
    country = (request.args.get("country") or "").strip()
    category = (request.args.get("category") or "").strip()
    abv_min = request.args.get("abv_min", type=float)
    abv_max = request.args.get("abv_max", type=float)

    query = Drink.query
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(Drink.name_es).like(like) |
            func.lower(Drink.name_en).like(like) |
            func.lower(Drink.fun_fact_es).like(like) |
            func.lower(Drink.origin_country).like(like)
        )
    if country:
        query = query.filter(func.lower(Drink.origin_country).like(f"%{country.lower()}%"))
    if category:
        query = query.filter(Drink.category == category)
    if abv_min is not None:
        if abv_min == 0:
            # 0%指定のときは「ノンアルも含めたい」ケースが多いのでNULL許容
            query = query.filter((Drink.abv >= 0) | (Drink.abv.is_(None)))
        else:
            query = query.filter(Drink.abv >= abv_min)
    if abv_max is not None:
        if abv_max == 0:
            query = query.filter(Drink.abv.is_(None))
        else:
            query = query.filter(Drink.abv <= abv_max)

    # ← コレが無いと NameError になる
    items = query.order_by(Drink.name_es.asc()).all()

    return render_template(
        "drinks.html",
        drinks=items,  # テンプレ側は {% for d in drinks %} なのでOK
        q=q, country=country, category=category,
        abv_min=abv_min if abv_min is not None else "",
        abv_max=abv_max if abv_max is not None else "",
        categories=CATEGORIES
    )


@app.route("/drink/<id>")
def detail(id):
    d = Drink.query.get(id)
    if not d:
        return render_template("notfound.html"), 404
    return render_template("detail.html", d=d)

@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        name_es = (request.form.get("name_es") or "").strip()
        origin_country = (request.form.get("origin_country") or "").strip()
        category = (request.form.get("category") or "").strip()
        serve_temp = request.form.get("serve_temp")  # ← ラジオの値を取得

        # 必須チェック
        if not name_es or not origin_country or not category or not serve_temp:
            flash("必須: 名前(ES) / 国 / カテゴリ / 提供温度", "warning")
            return redirect(url_for("add"))

        # 2択チェック
        if serve_temp not in ("fría", "caliente"):
            flash("提供温度は fría / caliente のみ選べます。", "warning")
            return redirect(url_for("add"))

        new_id = unique_id_from(name_es)

        d = Drink(
            id=new_id,
            name_es=name_es,
            name_en=None,
            origin_country=origin_country,
            category=category,
            abv=(float(request.form["abv"]) if request.form.get("abv") else None),
            serve_temp=serve_temp,           # ← ここで保存
            scene=None,
            fun_fact_es=(request.form.get("fun_fact_es") or None),
            image_url=(request.form.get("image_url") or None),
        )
        db.session.add(d)
        db.session.commit()
        flash("追加しました。", "success")
        return redirect(url_for("detail", id=new_id))

    return render_template("add.html", categories=CATEGORIES)
@app.route("/delete/<id>", methods=["POST"])
def delete(id):
    d = Drink.query.get(id)
    if not d:
        flash("対象が見つかりません。", "warning")
        return redirect(url_for("drinks"))
    db.session.delete(d)
    db.session.commit()
    flash("削除しました。", "success")
    return redirect(url_for("drinks"))


if __name__ == "__main__":
    app.run(debug=True)
