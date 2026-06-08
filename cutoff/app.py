import pickle
import re
import secrets
import time
import warnings
from functools import wraps
from pathlib import Path
from sklearn.preprocessing import LabelEncoder
import pandas as pd
import numpy as np
from flask import Flask, render_template, request, session, redirect, url_for
import sqlite3

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

app = Flask(__name__)
app.secret_key = "college-recommendation-secret-key"
app.config["TEMPLATES_AUTO_RELOAD"] = True

CASTE_COLUMNS = {
    0: "BC",
    1: "BCM",
    2: "MBC",
    3: "OC",
    4: "SC",
    5: "SCA",
    6: "ST",
}


def load_branch_map():
    html_path = Path(__file__).parent / "templates" / "input.html"
    html = html_path.read_text(encoding="utf-8")
    branch_select = re.search(
        r'<select id="branch" name="branch">(.*?)</select>', html, re.DOTALL
    )
    if not branch_select:
        return {}
    pairs = re.findall(
        r'<option value="(\d+)">([^<]+)</option>', branch_select.group(1)
    )
    return {int(value): label.strip() for value, label in pairs}


BRANCH_MAP = load_branch_map()

RESULTS_STORE = {}
RESULTS_TTL_SECONDS = 3600


def cleanup_old_results():
    now = time.time()
    expired = [
        result_id
        for result_id, payload in RESULTS_STORE.items()
        if now - payload.get("created", now) > RESULTS_TTL_SECONDS
    ]
    for result_id in expired:
        RESULTS_STORE.pop(result_id, None)


def store_results(payload):
    cleanup_old_results()
    result_id = secrets.token_urlsafe(16)
    RESULTS_STORE[result_id] = {"created": time.time(), **payload}
    session["result_id"] = result_id
    for key in (
        "result_type",
        "college_results",
        "college_details",
        "recommended_college",
        "caste_label",
        "department_results",
        "recommended_department",
        "branch_error",
    ):
        session.pop(key, None)
    session.modified = True
    return result_id


def get_results():
    result_id = session.get("result_id")
    if not result_id:
        return None
    return RESULTS_STORE.get(result_id)


def get_departments_from_csv(df, college_code, caste_column, cutoff):
    college_rows = df[df["College Code"] == college_code]
    caste_values = pd.to_numeric(college_rows[caste_column], errors="coerce")
    eligible = college_rows[caste_values.notna() & (caste_values <= cutoff)].copy()
    eligible["caste_cutoff"] = caste_values[eligible.index]

    departments = []
    seen_branch_codes = set()
    for _, row in eligible.sort_values("caste_cutoff").iterrows():
        branch_code = row["Branch Code"]
        if branch_code in seen_branch_codes:
            continue
        seen_branch_codes.add(branch_code)
        departments.append(
            {
                "name": str(row["Branch Name"]).strip(),
                "branch_code": branch_code,
                "cutoff": row["caste_cutoff"],
            }
        )
    return departments


def match_branch_mask(branch_series, branch_label):
    branch_key = branch_label.upper().strip()
    mask = branch_series == branch_key
    if mask.any():
        return mask

    simplified = (
        branch_key.replace("(SS)", "")
        .replace("ENGG.", "ENGINEERING")
        .replace("  ", " ")
        .strip()
    )
    return branch_series.str.contains(re.escape(simplified[:40]), na=False, regex=True)


def get_colleges_from_csv(df, branch_label, caste_column, cutoff):
    branch_series = df["Branch Name"].astype(str).str.upper().str.strip()
    mask = match_branch_mask(branch_series, branch_label)
    caste_values = pd.to_numeric(df[caste_column], errors="coerce")
    eligible = df[mask & caste_values.notna() & (caste_values <= cutoff)].copy()
    eligible["caste_cutoff"] = caste_values[eligible.index]

    colleges = []
    seen_codes = set()
    for _, row in eligible.sort_values("caste_cutoff", ascending=False).iterrows():
        code = int(row["College Code"])
        if code in seen_codes:
            continue
        seen_codes.add(code)
        colleges.append(
            {
                "name": str(row["College Name"]).split(",")[0],
                "college_code": code,
                "cutoff": round(float(row["caste_cutoff"]), 2),
            }
        )
    return colleges


def mark_recommended_college(colleges, predicted_code):
    recommended = None
    for college in colleges:
        college["recommended"] = college["college_code"] == predicted_code
        if college["recommended"]:
            recommended = college["name"]
    return colleges, recommended

NO_CACHE_ENDPOINTS = {
    "index", "input", "show", "collge_name", "branch_name", "show_results",
    "logout", "login", "register", "reset_password",
}

@app.after_request
def set_cache_headers(response):
    if request.endpoint in NO_CACHE_ENDPOINTS:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped_view

def guest_only(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("logged_in"):
            return redirect(url_for("input"))
        return view(*args, **kwargs)
    return wrapped_view

@app.route('/')
@guest_only
def index():
    return render_template("register.html")

database = "new.db"
conn = sqlite3.connect(database)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS register (username TEXT, usermail TEXT, password INT)")
conn.commit()

@app.route('/register', methods=['POST'])
def register():
    if session.get("logged_in"):
        return redirect(url_for("input"))
    username=request.form["username"]
    usermail=request.form["usermail"]
    password=request.form["password"]
    conn = sqlite3.connect(database)
    cur = conn.cursor()
    cur.execute("INSERT INTO register (username, usermail, password) VALUES (?, ?, ?)", (username, usermail, password))
    conn.commit()
    return render_template("register.html")

@app.route('/reset_password', methods=['POST'])
def reset_password():
    if session.get("logged_in"):
        return redirect(url_for("input"))
    usermail=request.form["usermail"]
    password=request.form["confirm_password"]
    conn = sqlite3.connect(database)
    cur = conn.cursor()
    cur.execute("UPDATE register SET password=? WHERE usermail=?", (password, usermail))
    conn.commit()
    return render_template("register.html")







@app.route('/login', methods=['POST'])
def login():
    if session.get("logged_in"):
        return redirect(url_for("input"))
    usermail = request.form["usermail"]
    password = request.form["password"]
    conn = sqlite3.connect(database)
    cur = conn.cursor()
    cur.execute("SELECT * FROM register WHERE usermail=? AND password=?", (usermail, password))
    data = cur.fetchone()
    if data:
        session["logged_in"] = True
        session["usermail"] = usermail
        return redirect(url_for("input"))
    return render_template(
        "register.html",
        error="Password mismatch. Please check your email and password.",
        active_form="login-form",
    )

@app.route("/logout")
def logout():
    result_id = session.get("result_id")
    if result_id:
        RESULTS_STORE.pop(result_id, None)
    session.clear()
    return redirect(url_for("index"))

CLASSES={0:"BC_model",1:"BCM_model",2:"MBC_model",3:"OC_model",4:"SC_model",5:"SCA_model",6:"ST_model"}

@app.route('/input', methods=['POST','GET'])
@login_required
def input():
    return render_template('input.html')

@app.route('/collge_name',methods=["GET","POST"])
@login_required
def collge_name():
    if request.method == "GET":
        return redirect(url_for("show_results"))

    CUTOFF=int(request.form["cutoff"])
    branchcode=int(request.form["branch"])
    CASTE=int(request.form["CASTE"])
    model_name = CLASSES[CASTE]
    data = np.array([[CUTOFF,branchcode]])
    with open(f'models1/{model_name}.pkl', 'rb') as file:
        loaded_model = pickle.load(file)
    y_pred = loaded_model.predict(data)
    final = round(y_pred[0])
    df = pd.read_csv("combined_cutoff.csv")
    branch_label = BRANCH_MAP.get(branchcode, "")
    caste_column = CASTE_COLUMNS[CASTE]
    colleges = get_colleges_from_csv(df, branch_label, caste_column, CUTOFF)
    colleges, recommended = mark_recommended_college(colleges, final)

    predicted_rows = df[
        (df["College Code"] == final)
        & match_branch_mask(df["Branch Name"].astype(str).str.upper().str.strip(), branch_label)
    ]
    predicted_eligible = False
    predicted_cutoff = None
    if not predicted_rows.empty:
        predicted_cutoff_values = pd.to_numeric(predicted_rows[caste_column], errors="coerce")
        valid_predicted = predicted_cutoff_values.dropna()
        if not valid_predicted.empty:
            predicted_cutoff = round(float(valid_predicted.min()), 2)
            predicted_eligible = predicted_cutoff <= CUTOFF

    print("=" * 60)
    print("[COLLEGE SEARCH] Request received")
    print(f"  Cutoff     : {CUTOFF}")
    print(f"  Branch code: {branchcode} ({branch_label or 'unknown branch'})")
    print(f"  Caste      : {CASTE} ({model_name}, column={caste_column})")
    print(f"  Predicted college code (model output): {final}")
    print(f"  Predicted college eligible for branch: {predicted_eligible}")
    if predicted_cutoff is not None:
        print(f"  Predicted college {caste_column} cutoff: {predicted_cutoff}")
    print(f"  Recommended college: {recommended}")
    print(f"  Lookup source: csv+model-rank")
    print(f"  Colleges found: {len(colleges)}")
    for idx, college in enumerate(colleges[:25], 1):
        marker = " *" if college.get("recommended") else ""
        print(
            f"    [{idx}] {caste_column}={college['cutoff']} "
            f"code={college['college_code']} {college['name']}{marker}"
        )
    if len(colleges) > 25:
        print(f"    ... and {len(colleges) - 25} more")
    print("[BACKEND OUTPUT] Sending to output.html:")
    print(f"  result_type=college, count={len(colleges)}, recommended={recommended!r}")
    print("=" * 60)

    store_results(
        {
            "result_type": "college",
            "college_results": [college["name"] for college in colleges],
            "college_details": colleges,
            "recommended_college": recommended,
            "caste_label": caste_column,
        }
    )
    return redirect(url_for("show_results"))


cutoff_data = pd.read_csv('combined_cutoffs.csv')

@app.route('/branch_name',methods=["GET","POST"])
@login_required
def branch_name():
    if request.method == "GET":
        return redirect(url_for("show_results"))

    CUTOFF=int(request.form["cutoff"])
    collge_code=int(request.form["collge_code"])
    CASTE=int(request.form["CASTE"])
    k=set(cutoff_data["College Code"])
    if collge_code not in k:
        print("=" * 60)
        print("[DEPARTMENT SEARCH] Invalid college code:", collge_code)
        print("[BACKEND OUTPUT] Sending to output.html:")
        print("  result_type=department, branch_name=None, branch_error='College code not applicable'")
        print("=" * 60)
        store_results(
            {
                "result_type": "department",
                "department_results": [],
                "recommended_department": None,
                "branch_error": "College code not applicable. Please check the code and try again.",
            }
        )
        return redirect(url_for("show_results"))
    model_name = CLASSES[CASTE]
    caste_column = CASTE_COLUMNS[CASTE]
    data = np.array([[CUTOFF, collge_code]])
    with open(f'models2/{model_name}.pkl', 'rb') as file:
        loaded_model = pickle.load(file)
    y_pred = loaded_model.predict(data)
    final = round(y_pred[0])
    le_branch = LabelEncoder()
    branch_df = cutoff_data.copy()
    branch_df["b_code"] = le_branch.fit_transform(branch_df["Branch Code"])
    branch_mapping = dict(zip(branch_df["b_code"], branch_df["Branch Name"]))

    predicted_branch_name = branch_mapping.get(final)
    predicted_branch_code = None
    if predicted_branch_name:
        predicted_rows = branch_df[branch_df["b_code"] == final]
        if not predicted_rows.empty:
            predicted_branch_code = predicted_rows["Branch Code"].iloc[0]

    departments = get_departments_from_csv(cutoff_data, collge_code, caste_column, CUTOFF)
    recommended = None
    if predicted_branch_code:
        for dept in departments:
            if dept["branch_code"] == predicted_branch_code:
                recommended = dept["name"]
                break

    department_names = [dept["name"] for dept in departments]
    if recommended and recommended in department_names:
        department_names = [recommended] + [
            name for name in department_names if name != recommended
        ]

    branch_error = None
    if not department_names:
        branch_error = "No departments found for your cutoff at this college."

    print("=" * 60)
    print("[DEPARTMENT SEARCH] Request received")
    print(f"  Cutoff      : {CUTOFF}")
    print(f"  College code: {collge_code}")
    print(f"  Caste       : {CASTE} ({model_name})")
    print(f"  Predicted branch code (model output): {final}")
    print(f"  Predicted branch name (global): {predicted_branch_name}")
    print(f"  Predicted branch code (global): {predicted_branch_code}")
    print(f"  Recommended at this college: {recommended}")
    print(f"  Eligible departments: {len(department_names)}")
    for idx, name in enumerate(department_names, 1):
        print(f"    [{idx}] {name}")
    print("[BACKEND OUTPUT] Sending to output.html:")
    print(f"  result_type=department, departments={department_names!r}, recommended={recommended!r}, branch_error={branch_error!r}")
    print("=" * 60)
    store_results(
        {
            "result_type": "department",
            "department_results": department_names,
            "recommended_department": recommended,
            "branch_error": branch_error,
        }
    )
    return redirect(url_for("show_results"))

@app.route("/results")
@login_required
def show_results():
    data = get_results()
    if not data:
        print("[BACKEND OUTPUT] GET /results — no data found, redirecting to /input")
        return redirect(url_for("input"))

    result_type = data.get("result_type")
    if result_type == "college":
        colleges = data.get("college_results") or []
        college_details = data.get("college_details") or []
        recommended = data.get("recommended_college")
        caste_label = data.get("caste_label", "Cutoff")
        print("[BACKEND OUTPUT] GET /results — rendering college list")
        print(f"  result_type=college, count={len(colleges)}, recommended={recommended!r}")
        return render_template(
            "output.html",
            result_type="college",
            collegename=colleges,
            college_details=college_details,
            recommended_college=recommended,
            caste_label=caste_label,
            result_count=len(colleges),
        )
    if result_type == "department":
        departments = data.get("department_results") or []
        recommended = data.get("recommended_department")
        error = data.get("branch_error")
        print("[BACKEND OUTPUT] GET /results — rendering department list")
        print(f"  result_type=department, count={len(departments)}, recommended={recommended!r}, branch_error={error!r}")
        return render_template(
            "output.html",
            result_type="department",
            department_results=departments,
            recommended_department=recommended,
            result_count=len(departments),
            branch_error=error,
        )
    print("[BACKEND OUTPUT] GET /results — unknown result type, redirecting to /input")
    return redirect(url_for("input"))

@app.route('/show')
@login_required
def show():
    return render_template('cutoffdata.html', data=cutoff_data.to_dict(orient='records'))
      

if __name__ == '__main__':
    app.run(debug=False,port=500)
