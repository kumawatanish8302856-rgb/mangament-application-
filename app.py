from flask import Flask, render_template, request, redirect, jsonify, send_file
import sqlite3
from datetime import datetime

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

app = Flask(__name__)

# ---------------- DB ----------------
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_no TEXT,
    item TEXT,
    qty REAL,
    price  REAL,
    status TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS menu (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        full_price REAL,
        half_price REAL
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- HOME ----------------
@app.route('/')
def home():
    return render_template("home.html")


# ---------------- MENU ----------------
@app.route('/menu')
def menu_page():
    conn = get_db()
    items = conn.execute("SELECT * FROM menu").fetchall()
    conn.close()
    return render_template("menu.html", items=items)


@app.route('/add_menu', methods=['POST'])
def add_menu():
    name = request.form['name']
    full = int(request.form['full'])
    half = int(request.form['half'])

    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO menu (name, full_price, half_price)
        VALUES (?, ?, ?)
    """, (name.lower(), full, half))

    conn.commit()
    conn.close()
    return redirect('/menu')


@app.route('/search_menu')
def search_menu():
    q = request.args.get('q', '').lower()

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM menu WHERE name LIKE ? LIMIT 10",
        (f"%{q}%",)
    ).fetchall()
    conn.close()

    return jsonify([
        {
            "name": r["name"].title(),
            "full": r["full_price"],
            "half": r["half_price"]
        } for r in rows
    ])


# ---------------- WAITER ----------------
@app.route('/waiter')
def waiter():
    table_no = request.args.get('table')

    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE status!='paid'").fetchall()
    conn.close()

    tables = {}

    for r in rows:
        t = r["table_no"]
        tables.setdefault(t, {"orders": [], "status": "pending"})
        tables[t]["orders"].append(r)

        if r["status"] == "preparing":
            tables[t]["status"] = "preparing"
        elif r["status"] == "ready" and tables[t]["status"] != "preparing":
            tables[t]["status"] = "ready"

    orders = tables.get(table_no, {}).get("orders", []) if table_no else []

    return render_template(
        "waiter.html",
        tables=tables,
        orders=orders,
        table_no=table_no
    )


# ---------------- ADD ITEM ----------------
@app.route('/add_item/<table_no>', methods=['POST'])
def add_item(table_no):
    item = request.form['item']
    qty = float(request.form['qty'])
    type_ = request.form['type']

    conn = get_db()

    menu_item = conn.execute(
        "SELECT * FROM menu WHERE name=?",
        (item.lower(),)
    ).fetchone()

    price = 0
    if menu_item:
        price = menu_item['full_price'] if type_ == "Full" else menu_item['half_price']

    item_name = f"{item} ({type_})"

    existing = conn.execute("""
        SELECT * FROM orders
        WHERE table_no=? AND item=? AND status!='paid'
    """, (table_no, item_name)).fetchone()

    if existing:
        conn.execute("""
            UPDATE orders SET qty = qty + ?
             SET qty = qty + ?,
            status = 'pending',
            created_at = datetime('now')
            WHERE id=?
        """, (qty, existing['id']))
    else:
        conn.execute("""
    INSERT INTO orders (table_no, item, qty, price, status, created_at)
    VALUES (?, ?, ?, ?, 'pending', datetime('now'))
""", (table_no, item_name, qty, price))

    conn.commit()
    conn.close()

    return redirect(f'/waiter?table={table_no}')


# ---------------- DELETE ----------------
@app.route('/delete/<int:id>/<table_no>')
def delete(id, table_no):
    conn = get_db()
    conn.execute("DELETE FROM orders WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(f'/waiter?table={table_no}')


# ---------------- CHEF ----------------
@app.route('/chef')
def chef():
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE status!='paid'").fetchall()
    conn.close()

    tables = {}
    for r in rows:
        tables.setdefault(r["table_no"], []).append(r)

    return render_template("chef.html", tables=tables)


# ---------------- UPDATE STATUS ----------------
@app.route('/update_table/<table_no>/<status>')
def update_table(table_no, status):
    conn = get_db()
    conn.execute("""
        UPDATE orders SET status=?
        WHERE table_no=? AND status!='paid'
    """, (status, table_no))

    conn.commit()
    conn.close()
    return redirect('/chef')


# ---------------- RECEPTION ----------------
@app.route('/reception')
def reception():
    conn = get_db()
    rows = conn.execute("SELECT * FROM orders WHERE status='ready'").fetchall()
    conn.close()

    tables = {}
    for r in rows:
        tables.setdefault(r["table_no"], []).append(r)

    return render_template("reception.html", tables=tables)


# ---------------- BILL ----------------
@app.route('/bill/<table_no>')
def bill(table_no):
    conn = get_db()

    orders = conn.execute("""
        SELECT * FROM orders
        WHERE table_no=? AND status!='paid'
    """, (table_no,)).fetchall()

    conn.close()

    return render_template(
        "bill.html",
        orders=orders,
        table_no=table_no
    )


# ---------------- CALCULATE (FIXED) ----------------
@app.route('/calculate/<table_no>', methods=['POST'])
def calculate(table_no):
    items = request.form.getlist('item')
    quantities = request.form.getlist('qty')
    prices = request.form.getlist('price')

    total = 0
    bill_orders = []

    for item, qty, price in zip(items, quantities, prices):
        if not price:
            continue

        qty = float(qty)
        price = float(price)

        item_total = qty * price
        total += item_total

        bill_orders.append({
            "item": item,
            "qty": qty,
            "price": price,
            "total": item_total
        })

    gst = round(total * 0.18, 2)
    final = round(total + gst, 2)

    return render_template(
        "bill.html",
        orders=bill_orders,
        table_no=table_no,
        total=total,
        gst=gst,
        final=final
    )


# ---------------- PAYMENT ----------------
@app.route('/payment_done/<table_no>')
def payment_done(table_no):
    conn = get_db()
    conn.execute("""
        UPDATE orders SET status='paid'
        WHERE table_no=?
    """, (table_no,))
    conn.commit()
    conn.close()

    return redirect('/reception')


# ---------------- INVOICE ----------------
@app.route('/invoice/<table_no>')
def invoice(table_no):
    conn = get_db()

    orders = conn.execute("""
        SELECT * FROM orders
        WHERE table_no=? AND status!='paid'
    """, (table_no,)).fetchall()

    conn.close()

    file_path = f"invoice_{table_no}.pdf"

    doc = SimpleDocTemplate(file_path, pagesize=A4)
    styles = getSampleStyleSheet()

    elements = [
        Paragraph("<b>RMS Restaurant</b>", styles['Title']),
        Paragraph("Rajsamand, Rajasthan", styles['Normal']),
        Spacer(1, 10),
        Paragraph(f"Table {table_no}", styles['Heading2']),
        Paragraph(datetime.now().strftime('%d-%m-%Y %H:%M'), styles['Normal']),
        Spacer(1, 10)
    ]

    data = [["Item", "Qty", "Price", "Total"]]
    total = 0

    for o in orders:
        t = o['qty'] * o['price']
        data.append([o['item'], o['qty'], f"₹{o['price']}", f"₹{t}"])
        total += t

    gst = round(total * 0.18, 2)
    final = total + gst

    data += [
        ["", "", "Subtotal", f"₹{total}"],
        ["", "", "GST", f"₹{gst}"],
        ["", "", "Total", f"₹{final}"]
    ]

    table = Table(data)
    table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white)
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Thank you!", styles['Normal']))

    doc.build(elements)

    return send_file(file_path, as_attachment=True)



    # anyaltic
@app.route('/analytics')
def analytics():
    conn = get_db()
    cursor = conn.cursor()

    # ---------------- TODAY ----------------
    today_sales = cursor.execute("""
        SELECT SUM(qty * price)
        FROM orders
        WHERE status='paid'
        AND date(created_at)=date('now')
    """).fetchone()[0] or 0

    # ---------------- YESTERDAY ----------------
    yesterday_sales = cursor.execute("""
        SELECT SUM(qty * price)
        FROM orders
        WHERE status='paid'
        AND date(created_at)=date('now','-1 day')
    """).fetchone()[0] or 0

    # ---------------- WEEK ----------------
    week_sales = cursor.execute("""
        SELECT SUM(qty * price)
        FROM orders
        WHERE status='paid'
        AND date(created_at) >= date('now','-7 day')
    """).fetchone()[0] or 0

    # ---------------- MONTH ----------------
    month_sales = cursor.execute("""
        SELECT SUM(qty * price)
        FROM orders
        WHERE status='paid'
        AND strftime('%Y-%m', created_at)=strftime('%Y-%m','now')
    """).fetchone()[0] or 0

    # ---------------- CHART DATA (7 DAYS) ----------------
    cursor.execute("""
        SELECT date(created_at), SUM(qty * price)
        FROM orders
        WHERE status='paid'
        GROUP BY date(created_at)
        ORDER BY date(created_at) DESC
        LIMIT 7
    """)

    data = cursor.fetchall()
    data.reverse()

    labels = [row[0] for row in data]
    values = [row[1] or 0 for row in data]

    # ---------------- TOP ITEMS ----------------
    cursor.execute("""
        SELECT item, SUM(qty)
        FROM orders
        WHERE status='paid'
        GROUP BY item
        ORDER BY SUM(qty) DESC
        LIMIT 5
    """)

    top_items = cursor.fetchall()

    conn.close()

    return render_template(
    "analytics.html",
    today=today_sales,
    yesterday=yesterday_sales,
    week_sales=week_sales,
    month_sales=month_sales,
    labels=labels,
    values=values,
    top_items=top_items
)
# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
