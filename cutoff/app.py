import pickle
from sklearn.preprocessing import LabelEncoder
import pandas as pd
import numpy as np
from flask import Flask, render_template, request
import sqlite3
app = Flask(__name__)

@app.route('/')
def index():
    return render_template("register.html")

database = "new.db"
conn = sqlite3.connect(database)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS register (username TEXT, usermail TEXT, password INT)")
conn.commit()

@app.route('/register', methods=['POST'])
def register():
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
    usermail=request.form["usermail"]
    password=request.form["confirm_password"]
    conn = sqlite3.connect(database)
    cur = conn.cursor()
    cur.execute("UPDATE register SET password=? WHERE usermail=?", (password, usermail))
    conn.commit()
    return render_template("register.html")


@app.route('/login', methods=['POST'])
def login():
    usermail = request.form["usermail"]
    password = request.form["password"]
    conn = sqlite3.connect(database)
    cur = conn.cursor()
    cur.execute("SELECT * FROM register WHERE usermail=? AND password=?", (usermail, password))
    data = cur.fetchone()  
    print(data)
    if data:
        return render_template("input.html")
    else:
        return "Password mismatch"



CLASSES={0:"BC_model",1:"BCM_model",2:"MBC_model",3:"OC_model",4:"SC_model",5:"SCA_model",6:"ST_model"}

@app.route('/input', methods=['POST','GET'])
def input():
    return render_template('input.html')

@app.route('/collge_name',methods=["GET","POST"])
def collge_name():
    CUTOFF=int(request.form["cutoff"])
    branchcode=int(request.form["branch"])
    CASTE=int(request.form["CASTE"])
    model_name = CLASSES[CASTE]
    data = np.array([[CUTOFF,branchcode]])
    with open(f'models1/{model_name}.pkl', 'rb') as file:
        loaded_model = pickle.load(file)
    y_pred = loaded_model.predict(data)
    final=round(y_pred[0])
    college_code_column = "College Code"
    college_name_column = "College Name"     
    df = pd.read_csv("combined_cutoff.csv")
    def get_college_name(college_code):
        college_row = df[df[college_code_column] == college_code]
        if not college_row.empty:
            college_name = college_row[college_name_column].iloc[0]
            return college_name
        else:
            return None

    a=[]
    for i in range(final,final+1000,101):
        college_code_input = i
        college_name_output = get_college_name(college_code_input)
        a.append(college_name_output)
    b=set(a)
    a=[]
    for college_info in b:
        if college_info is not None:
            college_name = college_info.split(',')[0]
            a.append(college_name)
    print(a)
    return render_template("output.html",collegename=a,status=0)


cutoff_data = pd.read_csv('combined_cutoffs.csv')

@app.route('/branch_name',methods=["GET","POST"])
def branch_name():
    CUTOFF=int(request.form["cutoff"])
    collge_code=int(request.form["collge_code"])
    CASTE=int(request.form["CASTE"])
    k=set(cutoff_data["College Code"])
    if collge_code not in k:
        return "collge code not applicable"
    model_name = CLASSES[CASTE]
    data = np.array([[CUTOFF,collge_code]])
    with open(f'models2/{model_name}.pkl', 'rb') as file:
        loaded_model = pickle.load(file)
    y_pred = loaded_model.predict(data)
    final=round(y_pred[0])
    le_branch = LabelEncoder()
    cutoff_data['b_code'] = le_branch.fit_transform(cutoff_data["Branch Code"])
    branch_mapping = dict(zip(cutoff_data['b_code'], cutoff_data['Branch Name']))
    if final in branch_mapping:
        branch_name = branch_mapping[final]
        print(branch_name)
        return render_template("output.html",branch_name=branch_name,status=1)

@app.route('/show')
def show():
    return render_template('cutoffdata.html', data=cutoff_data.to_dict(orient='records'))
      

if __name__ == '__main__':
    app.run(debug=False,port=500)
