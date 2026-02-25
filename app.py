from flask import Flask, render_template, request, redirect, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

# ================= DATABASE =================
db = mysql.connector.connect(
    host=Config.DB_HOST,
    user=Config.DB_USER,
    password=Config.DB_PASSWORD,
    database=Config.DB_NAME
)
cursor = db.cursor(dictionary=True)

# ================= LOGIN =================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], password):
            session['id_user'] = user['id_user']
            session['role'] = user['role']
            session['nama'] = user['nama']

            if user['role'] == 'admin':
                return redirect('/admin')
            else:
                return redirect('/aspirasi')

        return "Login gagal"

    return render_template('login.html')

# ================= REGISTER =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama = request.form['nama']
        nis = request.form['nis']
        kelas = request.form['kelas']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        cursor.execute(
            "INSERT INTO users (nama, username, password, role) VALUES (%s,%s,%s,'siswa')",
            (nama, username, password)
        )
        db.commit()

        id_user = cursor.lastrowid

        cursor.execute(
            "INSERT INTO siswa (id_user, nis, kelas) VALUES (%s,%s,%s)",
            (id_user, nis, kelas)
        )
        db.commit()

        return redirect('/')

    return render_template('register.html')

# ================= ASPIRASI SISWA =================
@app.route('/aspirasi', methods=['GET', 'POST'])
def aspirasi():
    if session.get('role') != 'siswa':
        return redirect('/')

    if request.method == 'POST':
        judul = request.form['judul']
        kategori = request.form['kategori']
        isi = request.form['isi']

        cursor.execute(
            "SELECT id_siswa FROM siswa WHERE id_user=%s",
            (session['id_user'],)
        )
        siswa = cursor.fetchone()

        cursor.execute("""
            INSERT INTO aspirasi (id_siswa, judul, kategori, isi)
            VALUES (%s,%s,%s,%s)
        """, (siswa['id_siswa'], judul, kategori, isi))
        db.commit()

    cursor.execute("""
        SELECT 
            aspirasi.*,
            DATE_FORMAT(aspirasi.tanggal, '%d-%m-%Y %H:%i') AS tanggal_format
        FROM aspirasi
        JOIN siswa ON aspirasi.id_siswa = siswa.id_siswa
        WHERE siswa.id_user = %s
        ORDER BY aspirasi.tanggal DESC
    """, (session['id_user'],))

    data = cursor.fetchall()
    return render_template('aspirasi.html', data=data)

# ================= HISTORI =================
@app.route('/histori')
def histori():
    if session.get('role') != 'siswa':
        return redirect('/')

    cursor.execute("""
        SELECT 
            a.id_aspirasi,
            a.judul,
            a.kategori,
            a.status,
            DATE_FORMAT(a.tanggal, '%d-%m-%Y') AS tanggal_format,
            uf.isi_feedback,
            uf.progres,
            DATE_FORMAT(uf.tanggal_feedback, '%d-%m-%Y') AS tanggal_feedback
        FROM aspirasi a
        JOIN siswa s ON a.id_siswa = s.id_siswa
        LEFT JOIN umpan_balik uf ON a.id_aspirasi = uf.id_aspirasi
        WHERE s.id_user = %s
        ORDER BY a.tanggal DESC
    """, (session['id_user'],))

    data = cursor.fetchall()
    return render_template('histori.html', data=data)

# ================= ADMIN DASHBOARD =================
@app.route('/admin')
def admin():
    if session.get('role') != 'admin':
        return redirect('/')

    sort = request.args.get('sort', 'tanggal')  # ambil param sort dari GET

    query = """
        SELECT 
            a.*,
            u.nama,
            s.kelas,
            DATE_FORMAT(a.tanggal, '%d-%m-%Y %H:%i') AS tanggal_format,
            DATE_FORMAT(a.tanggal, '%M %Y') AS bulan_tahun
        FROM aspirasi a
        JOIN siswa s ON a.id_siswa = s.id_siswa
        JOIN users u ON s.id_user = u.id_user
    """

    # logika sort
    if sort == 'kategori':
        query += " ORDER BY a.kategori ASC"
    elif sort == 'siswa':
        query += " ORDER BY u.nama ASC"
    elif sort == 'bulan':
        query += " ORDER BY YEAR(a.tanggal), MONTH(a.tanggal)"
    else:  # default = tanggal
        query += " ORDER BY a.tanggal DESC"

    cursor.execute(query)
    data = cursor.fetchall()
    return render_template('admin_dashboard.html', data=data)

# ================= FEEDBACK =================
@app.route('/feedback/<int:id>', methods=['GET', 'POST'])
def feedback(id):
    if session.get('role') != 'admin':
        return redirect('/')

    if request.method == 'POST':
        isi = request.form['isi']
        progres = request.form['progres']
        status = request.form['status']

        cursor.execute("""
            INSERT INTO umpan_balik (id_aspirasi, id_admin, isi_feedback, progres)
            VALUES (%s,%s,%s,%s)
        """, (id, session['id_user'], isi, progres))

        cursor.execute("""
            UPDATE aspirasi SET status=%s WHERE id_aspirasi=%s
        """, (status, id))

        db.commit()
        return redirect('/admin')

    cursor.execute("SELECT * FROM aspirasi WHERE id_aspirasi=%s", (id,))
    data = cursor.fetchone()
    return render_template('feedback.html', data=data)

# ================= LAPORAN PERBULAN =================
from flask import send_file
import io
import pdfkit

@app.route('/admin/laporan', methods=['GET'])
def laporan():
    if session.get('role') != 'admin':
        return redirect('/')

    bulan = request.args.get('bulan')  # format: 'YYYY-MM'
    
    query = """
        SELECT 
            a.judul, a.kategori, a.status,
            DATE_FORMAT(a.tanggal, '%d-%m-%Y') AS tanggal_aspirasi,
            u.nama, s.kelas,
            uf.isi_feedback, uf.progres,
            DATE_FORMAT(uf.tanggal_feedback, '%d-%m-%Y') AS tanggal_feedback
        FROM aspirasi a
        JOIN siswa s ON a.id_siswa = s.id_siswa
        JOIN users u ON s.id_user = u.id_user
        JOIN umpan_balik uf ON a.id_aspirasi = uf.id_aspirasi
    """
    params = []

    if bulan:
        query += " WHERE DATE_FORMAT(a.tanggal, '%Y-%m') = %s"
        params.append(bulan)

    query += " ORDER BY a.tanggal DESC"

    cursor.execute(query, tuple(params))
    data = cursor.fetchall()

    return render_template('laporan.html', data=data, bulan=bulan)
    
# ================= EXPORT LAPORAN KE PDF MENGGUNAKAN PDFKIT =================
@app.route('/admin/laporan/pdf', methods=['GET'])
def laporan_pdf():
    if session.get('role') != 'admin':
        return redirect('/')

    bulan = request.args.get('bulan')  # format: 'YYYY-MM'

    query = """
        SELECT 
            a.judul, a.kategori, a.status,
            DATE_FORMAT(a.tanggal, '%d-%m-%Y') AS tanggal_aspirasi,
            u.nama, s.kelas,
            uf.isi_feedback, uf.progres,
            DATE_FORMAT(uf.tanggal_feedback, '%d-%m-%Y') AS tanggal_feedback
        FROM aspirasi a
        JOIN siswa s ON a.id_siswa = s.id_siswa
        JOIN users u ON s.id_user = u.id_user
        JOIN umpan_balik uf ON a.id_aspirasi = uf.id_aspirasi
    """
    params = []

    if bulan:
        query += " WHERE DATE_FORMAT(a.tanggal, '%Y-%m') = %s"
        params.append(bulan)

    query += " ORDER BY a.tanggal DESC"

    cursor.execute(query, tuple(params))
    data = cursor.fetchall()

    # render template ke html
    html = render_template('laporan_pdf.html', data=data, bulan=bulan)

    # buat PDF menggunakan pdfkit
    pdf = pdfkit.from_string(html, False)  # False supaya return bytes
    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        download_name='laporan_aspirasi.pdf'
    )

# ================= LOGOUT =================
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
