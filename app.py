from flask import Flask, render_template, request, redirect, url_for
from deepface import DeepFace
import sqlite3
import os
import cv2
from datetime import datetime

app = Flask(__name__)

os.makedirs("uploads", exist_ok=True)
os.makedirs("od_letters", exist_ok=True)


# -----------------------------
# DATABASE
# -----------------------------

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
            face_image TEXT NOT NULL
        )
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


# -----------------------------
# HOME
# -----------------------------

@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------
# REGISTER
# -----------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        register_number = request.form["register_number"]
        department = request.form["department"]
        image = request.files["face_image"]

        if image.filename == "":
            return "Please select a face image."

        filename = register_number + "_" + image.filename

        image_path = os.path.join(
            "uploads",
            filename
        )

        image.save(image_path)

        connection = get_connection()
        cursor = connection.cursor()

        try:

            cursor.execute("""
                INSERT INTO students
                (name, register_number, department, face_image)
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

            return "Register number already exists."

        connection.close()

        return redirect(
            url_for("register_success")
        )

    return render_template("register.html")


@app.route("/register-success")
def register_success():

    return """
    <h2 style="text-align:center;margin-top:100px;">
        Student Registered Successfully! ✅
    </h2>

    <p style="text-align:center;">
        <a href="/register">Register Another Student</a>
        &nbsp;&nbsp;
        <a href="/">Home</a>
    </p>
    """


# -----------------------------
# ATTENDANCE
# -----------------------------

@app.route("/attendance", methods=["GET", "POST"])
def attendance():

    message = ""

    if request.method == "POST":

        image = request.files["face_image"]

        if image.filename == "":
            return render_template(
                "attendance.html",
                message="Please select an image."
            )

        temp_path = os.path.join(
            "uploads",
            "attendance_temp.jpg"
        )

        image.save(temp_path)

        attendance_image = cv2.imread(temp_path)

        if attendance_image is None:

            return render_template(
                "attendance.html",
                message="Unable to read the uploaded image."
            )

        connection = get_connection()
        cursor = connection.cursor()

        students = cursor.execute(
            "SELECT * FROM students"
        ).fetchall()

        today = datetime.now().strftime("%Y-%m-%d")
        current_time = datetime.now().strftime("%H:%M:%S")

        recognized_student = None

        for student in students:

            registered_image = cv2.imread(
                student["face_image"]
            )

            if registered_image is None:
                continue

            try:

                result = DeepFace.verify(
                    attendance_image,
                    registered_image,
                    model_name="Facenet",
                    detector_backend="opencv",
                    enforce_detection=False
                )

                if result["verified"]:

                    recognized_student = student
                    break

            except Exception as error:

                print(
                    "Face recognition error:",
                    error
                )

        if recognized_student:

            student_id = recognized_student["id"]

            # Check OD
            od_record = cursor.execute("""
                SELECT *
                FROM od_requests
                WHERE student_id = ?
                AND date = ?
            """, (
                student_id,
                today
            )).fetchone()

            if od_record:

                message = (
                    "Student is already marked as OD: "
                    + recognized_student["name"]
                )

            else:

                existing = cursor.execute("""
                    SELECT *
                    FROM attendance
                    WHERE student_id = ?
                    AND date = ?
                """, (
                    student_id,
                    today
                )).fetchone()

                if existing:

                    message = (
                        "Attendance already marked for "
                        + recognized_student["name"]
                    )

                else:

                    cursor.execute("""
                        INSERT INTO attendance
                        (student_id, date, time, status)
                        VALUES (?, ?, ?, ?)
                    """, (
                        student_id,
                        today,
                        current_time,
                        "Present"
                    ))

                    connection.commit()

                    message = (
                        "Attendance marked: "
                        + recognized_student["name"]
                        + " ✅"
                    )

        else:

            message = "Student not recognized ❌"

        connection.close()

        return render_template(
            "attendance.html",
            message=message
        )

    return render_template(
        "attendance.html",
        message=message
    )


# -----------------------------
# OD LETTER
# -----------------------------

@app.route("/od", methods=["GET", "POST"])
def od():

    message = ""

    connection = get_connection()
    cursor = connection.cursor()

    students = cursor.execute("""
        SELECT *
        FROM students
        ORDER BY register_number
    """).fetchall()

    if request.method == "POST":

        register_number = request.form["register_number"]
        od_date = request.form["date"]
        letter = request.files["letter"]

        student = cursor.execute("""
            SELECT *
            FROM students
            WHERE register_number = ?
        """, (
            register_number,
        )).fetchone()

        if student is None:

            connection.close()

            return render_template(
                "od.html",
                students=students,
                message="Student not found ❌"
            )

        if letter.filename == "":

            connection.close()

            return render_template(
                "od.html",
                students=students,
                message="Please upload the OD letter."
            )

        filename = (
            register_number
            + "_"
            + od_date
            + "_"
            + letter.filename
        )

        letter_path = os.path.join(
            "od_letters",
            filename
        )

        letter.save(letter_path)

        # Check whether OD already exists
        existing_od = cursor.execute("""
            SELECT *
            FROM od_requests
            WHERE student_id = ?
            AND date = ?
        """, (
            student["id"],
            od_date
        )).fetchone()

        if existing_od:

            cursor.execute("""
                UPDATE od_requests
                SET letter = ?, status = ?
                WHERE student_id = ?
                AND date = ?
            """, (
                letter_path,
                "OD",
                student["id"],
                od_date
            ))

        else:

            cursor.execute("""
                INSERT INTO od_requests
                (student_id, date, letter, status)
                VALUES (?, ?, ?, ?)
            """, (
                student["id"],
                od_date,
                letter_path,
                "OD"
            ))

        # IMPORTANT:
        # Remove old Present/Absent record
        # for the same student and date.

        cursor.execute("""
            DELETE FROM attendance
            WHERE student_id = ?
            AND date = ?
        """, (
            student["id"],
            od_date
        ))

        # Create only OD record

        cursor.execute("""
            INSERT INTO attendance
            (student_id, date, time, status)
            VALUES (?, ?, ?, ?)
        """, (
            student["id"],
            od_date,
            "-",
            "OD"
        ))

        connection.commit()
        connection.close()

        return render_template(
            "od.html",
            students=students,
            message=(
                "OD marked successfully for "
                + student["name"]
                + " ✅"
            )
        )

    connection.close()

    return render_template(
        "od.html",
        students=students,
        message=message
    )


# -----------------------------
# CLOSE ATTENDANCE
# -----------------------------

@app.route("/close-attendance", methods=["POST"])
def close_attendance():

    today = datetime.now().strftime("%Y-%m-%d")

    connection = get_connection()
    cursor = connection.cursor()

    students = cursor.execute(
        "SELECT * FROM students"
    ).fetchall()

    for student in students:

        student_id = student["id"]

        # Check OD
        od_record = cursor.execute("""
            SELECT *
            FROM od_requests
            WHERE student_id = ?
            AND date = ?
        """, (
            student_id,
            today
        )).fetchone()

        if od_record:

            # Remove any old attendance
            cursor.execute("""
                DELETE FROM attendance
                WHERE student_id = ?
                AND date = ?
            """, (
                student_id,
                today
            ))

            # Add OD only
            cursor.execute("""
                INSERT INTO attendance
                (student_id, date, time, status)
                VALUES (?, ?, ?, ?)
            """, (
                student_id,
                today,
                "-",
                "OD"
            ))

            continue

        # Check existing attendance

        existing = cursor.execute("""
            SELECT *
            FROM attendance
            WHERE student_id = ?
            AND date = ?
        """, (
            student_id,
            today
        )).fetchone()

        # Already Present
        if existing:
            continue

        # No Present and no OD
        # Mark Absent

        cursor.execute("""
            INSERT INTO attendance
            (student_id, date, time, status)
            VALUES (?, ?, ?, ?)
        """, (
            student_id,
            today,
            "-",
            "Absent"
        ))

    connection.commit()
    connection.close()

    return redirect(
        url_for("report")
    )


# -----------------------------
# REPORT
# -----------------------------

@app.route("/report")
def report():

    connection = get_connection()
    cursor = connection.cursor()

    # If OD exists for a student/date,
    # do not show an old Absent/Present record.

    records = cursor.execute("""
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
                SELECT 1
                FROM od_requests
                WHERE od_requests.student_id = attendance.student_id
                AND od_requests.date = attendance.date
            )
        )

        ORDER BY
            attendance.date DESC,
            students.register_number
    """).fetchall()

    connection.close()

    return render_template(
        "report.html",
        records=records
    )


# -----------------------------
# RUN
# -----------------------------

if __name__ == "__main__":

    app.run(debug=True)
