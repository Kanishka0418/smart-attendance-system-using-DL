from flask import Flask, render_template, request, redirect, url_for
from deepface import DeepFace
import sqlite3
import os
import cv2
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)

os.makedirs("uploads", exist_ok=True)
os.makedirs("od_letters", exist_ok=True)


# DATABASE

def get_connection():
    connection = sqlite3.connect("database.db", timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def create_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            register_number TEXT UNIQUE NOT NULL,
            department TEXT NOT NULL,
            current_year TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            previous_marks TEXT NOT NULL DEFAULT '',
            college_name TEXT NOT NULL DEFAULT '',
            current_semester TEXT NOT NULL DEFAULT '',
            previous_semester_cgpa TEXT NOT NULL DEFAULT '',
            face_image TEXT NOT NULL
        )
    """)

    # Add new columns safely to an existing database.
    columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(students)"
        ).fetchall()
    }

    new_columns = {
        "current_year": "TEXT NOT NULL DEFAULT ''",
        "semester": "TEXT NOT NULL DEFAULT ''",
        "previous_marks": "TEXT NOT NULL DEFAULT ''",
        "college_name": "TEXT NOT NULL DEFAULT ''",
        "current_semester": "TEXT NOT NULL DEFAULT ''",
        "previous_semester_cgpa": "TEXT NOT NULL DEFAULT ''"
    }

    for column, definition in new_columns.items():
        if column not in columns:
            cursor.execute(
                f"ALTER TABLE students ADD COLUMN {column} {definition}"
            )

    # Preserve any academic information already stored in old columns.
    cursor.execute("""
        UPDATE students
        SET current_semester = semester
        WHERE current_semester = '' AND semester != ''
    """)

    cursor.execute("""
        UPDATE students
        SET previous_semester_cgpa = previous_marks
        WHERE previous_semester_cgpa = '' AND previous_marks != ''
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS od_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            letter TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    connection.commit()
    connection.close()


create_database()
@app.route("/reset-all-data", methods=["GET", "POST"])
def reset_all_data():
    if request.method == "POST":
        connection = get_connection()

        connection.execute("DELETE FROM attendance")
        connection.execute("DELETE FROM od_requests")
        connection.execute("DELETE FROM students")

        connection.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('students', 'attendance', 'od_requests')"
        )

        connection.commit()
        connection.close()

        return "All student, attendance and OD records cleared."

    return """
    <h2>Delete all existing project records?</h2>
    <p>This will permanently clear students, attendance and OD records.</p>
    <form method="POST">
        <button type="submit">Confirm Delete All Data</button>
    </form>
    """


# HOME

@app.route("/")
def home():
    return render_template("index.html")


# REGISTER STUDENT - ONLY FOUR FIELDS

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        register_number = request.form.get(
            "register_number", ""
        ).strip()
        department = request.form.get("department", "").strip()
        image = request.files.get("face_image")

        if not all([name, register_number, department]):
            return render_template(
                "register.html",
                message="Please fill in all required details."
            )

        if not image or not image.filename:
            return render_template(
                "register.html",
                message="Please upload a face photo."
            )

        safe_register = secure_filename(register_number)

        if not safe_register:
            return render_template(
                "register.html",
                message="Invalid register number."
            )

        connection = get_connection()

        existing_student = connection.execute(
            "SELECT id FROM students WHERE register_number = ?",
            (register_number,)
        ).fetchone()

        if existing_student:
            connection.close()
            return render_template(
                "register.html",
                message="Register number already exists."
            )

        temp_path = os.path.join("uploads", "register_temp.jpg")
        filename = safe_register + "_face.jpg"
        image_path = os.path.join("uploads", filename)

        image.save(temp_path)

        try:
            faces = DeepFace.extract_faces(
                img_path=temp_path,
                detector_backend="opencv",
                enforce_detection=True
            )

            if not faces:
                raise ValueError("No face detected")

        except Exception:
            connection.close()

            if os.path.exists(temp_path):
                os.remove(temp_path)

            return render_template(
                "register.html",
                message="No face detected. Upload a clear face photo."
            )

        try:
            # Academic details are not requested on this form.
            # They can be populated separately in the database.
            connection.execute("""
                INSERT INTO students (
                    name, register_number, department,
                    face_image
                )
                VALUES (?, ?, ?, ?)
            """, (
                name,
                register_number,
                department,
                image_path
            ))

            connection.commit()

        except sqlite3.IntegrityError:
            connection.close()

            if os.path.exists(temp_path):
                os.remove(temp_path)

            return render_template(
                "register.html",
                message="Register number already exists."
            )

        connection.close()
        os.replace(temp_path, image_path)

        return redirect(url_for("register_success"))

    return render_template("register.html", message="")


@app.route("/register-success")
def register_success():
    return """
    <h2 style="text-align:center;margin-top:100px;">
        Student Registered Successfully!
    </h2>
    <p style="text-align:center;">
        <a href="/register">Register Another Student</a>
        &nbsp;&nbsp;
        <a href="/">Home</a>
    </p>
    """


# ATTENDANCE / FACE RECOGNITION

@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    if request.method == "POST":
        image = request.files.get("face_image")

        if not image or not image.filename:
            return render_template(
                "attendance.html",
                message="Please upload a face photo.",
                student=None
            )

        temp_path = os.path.join(
            "uploads", "attendance_temp.jpg"
        )
        image.save(temp_path)

        uploaded_image = cv2.imread(temp_path)

        if uploaded_image is None:
            return render_template(
                "attendance.html",
                message="Unable to read the image.",
                student=None
            )

        try:
            faces = DeepFace.extract_faces(
                img_path=temp_path,
                detector_backend="opencv",
                enforce_detection=True
            )

            if not faces:
                raise ValueError("No face detected")

        except Exception:
            return render_template(
                "attendance.html",
                message="No face detected. Upload a clear face photo.",
                student=None
            )

        connection = get_connection()
        recognized_student = None
        best_distance = None

        students = connection.execute(
            "SELECT * FROM students"
        ).fetchall()

        for student in students:
            registered_image = student["face_image"]

            if (
                not registered_image
                or not os.path.exists(registered_image)
            ):
                continue

            try:
                result = DeepFace.verify(
                    img1_path=temp_path,
                    img2_path=registered_image,
                    model_name="Facenet",
                    detector_backend="opencv",
                    enforce_detection=True
                )

                distance = result.get("distance")
                threshold = result.get("threshold")

                if (
                    isinstance(distance, (int, float))
                    and isinstance(threshold, (int, float))
                    and distance <= threshold
                ):
                    if (
                        best_distance is None
                        or distance < best_distance
                    ):
                        best_distance = distance
                        recognized_student = dict(student)

            except Exception as error:
                print("Face verification error:", error)

        if recognized_student is None:
            connection.close()
            return render_template(
                "attendance.html",
                message=(
                    "Face not recognized. Student is not registered."
                ),
                student=None
            )

        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")
        student_id = recognized_student["id"]

        od_record = connection.execute("""
            SELECT 1 FROM od_requests
            WHERE student_id = ? AND date = ?
        """, (student_id, today)).fetchone()

        existing = connection.execute("""
            SELECT 1 FROM attendance
            WHERE student_id = ? AND date = ?
        """, (student_id, today)).fetchone()

        if not od_record and not existing:
            connection.execute("""
                INSERT INTO attendance
                (student_id, date, time, status)
                VALUES (?, ?, ?, ?)
            """, (
                student_id, today, current_time, "Present"
            ))
            connection.commit()

        connection.close()

        # Send all six student details to attendance.html.
        # Empty database fields will display as "Not set".
        recognized_student["college_name"] = (
            recognized_student.get("college_name") or "Not set"
        )
        recognized_student["current_semester"] = (
            recognized_student.get("current_semester")
            or recognized_student.get("semester")
            or "Not set"
        )
        recognized_student["previous_semester_cgpa"] = (
            recognized_student.get("previous_semester_cgpa")
            or recognized_student.get("previous_marks")
            or "Not set"
        )

        return render_template(
            "attendance.html",
            message="Face matched. Student profile found.",
            student=recognized_student
        )

    return render_template(
        "attendance.html",
        message="",
        student=None
    )


# OD LETTER

@app.route("/od", methods=["GET", "POST"])
def od():
    connection = get_connection()

    students = connection.execute("""
        SELECT * FROM students ORDER BY register_number
    """).fetchall()

    if request.method == "POST":
        register_number = request.form.get(
            "register_number", ""
        ).strip()
        od_date = request.form.get("date", "")
        letter = request.files.get("letter")

        student = connection.execute("""
            SELECT * FROM students WHERE register_number = ?
        """, (register_number,)).fetchone()

        if student is None:
            connection.close()
            return render_template(
                "od.html",
                students=students,
                message="Student not found."
            )

        if not od_date:
            connection.close()
            return render_template(
                "od.html",
                students=students,
                message="Please select the OD date."
            )

        if not letter or not letter.filename:
            connection.close()
            return render_template(
                "od.html",
                students=students,
                message="Please upload the OD letter."
            )

        filename = (
            secure_filename(register_number) + "_"
            + secure_filename(od_date) + "_"
            + secure_filename(letter.filename)
        )

        letter_path = os.path.join("od_letters", filename)
        letter.save(letter_path)

        existing_od = connection.execute("""
            SELECT id FROM od_requests
            WHERE student_id = ? AND date = ?
        """, (student["id"], od_date)).fetchone()

        if existing_od:
            connection.execute("""
                UPDATE od_requests
                SET letter = ?, status = 'OD'
                WHERE student_id = ? AND date = ?
            """, (letter_path, student["id"], od_date))
        else:
            connection.execute("""
                INSERT INTO od_requests
                (student_id, date, letter, status)
                VALUES (?, ?, ?, ?)
            """, (
                student["id"], od_date, letter_path, "OD"
            ))

        connection.execute("""
            DELETE FROM attendance
            WHERE student_id = ? AND date = ?
        """, (student["id"], od_date))

        connection.execute("""
            INSERT INTO attendance
            (student_id, date, time, status)
            VALUES (?, ?, ?, ?)
        """, (student["id"], od_date, "-", "OD"))

        connection.commit()
        connection.close()

        return redirect(url_for("od"))

    connection.close()

    return render_template(
        "od.html",
        students=students,
        message=""
    )


# CLOSE ATTENDANCE

@app.route("/close-attendance", methods=["POST"])
def close_attendance():
    today = datetime.now().strftime("%Y-%m-%d")
    connection = get_connection()

    students = connection.execute(
        "SELECT * FROM students"
    ).fetchall()

    for student in students:
        student_id = student["id"]

        od_record = connection.execute("""
            SELECT 1 FROM od_requests
            WHERE student_id = ? AND date = ?
        """, (student_id, today)).fetchone()

        if od_record:
            connection.execute("""
                DELETE FROM attendance
                WHERE student_id = ? AND date = ?
            """, (student_id, today))

            connection.execute("""
                INSERT INTO attendance
                (student_id, date, time, status)
                VALUES (?, ?, ?, ?)
            """, (student_id, today, "-", "OD"))

            continue

        existing = connection.execute("""
            SELECT 1 FROM attendance
            WHERE student_id = ? AND date = ?
        """, (student_id, today)).fetchone()

        if not existing:
            connection.execute("""
                INSERT INTO attendance
                (student_id, date, time, status)
                VALUES (?, ?, ?, ?)
            """, (student_id, today, "-", "Absent"))

    connection.commit()
    connection.close()

    return redirect(url_for("report"))


# REPORT

@app.route("/report")
def report():
    connection = get_connection()

    records = connection.execute("""
        SELECT
            students.name,
            students.register_number,
            students.department,
            attendance.date,
            attendance.time,
            attendance.status
        FROM attendance
        JOIN students
        ON attendance.student_id = students.id
        WHERE NOT (
            attendance.status IN ('Absent', 'Present')
            AND EXISTS (
                SELECT 1 FROM od_requests
                WHERE od_requests.student_id = attendance.student_id
                AND od_requests.date = attendance.date
            )
        )
        ORDER BY attendance.date DESC,
                 students.register_number
    """).fetchall()

    connection.close()

    return render_template("report.html", records=records)


# RUN APP

if __name__ == "__main__":
    app.run(debug=True)

