import customtkinter as ctk
from tkinter import messagebox, filedialog
import sqlite3
import os
import shutil
import hashlib
import re
import ssl
import json
import base64
import smtplib
import time
import threading
import urllib.request
import urllib.parse
from email.message import EmailMessage
from datetime import datetime

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None


# ============================================================
# YOUR SETTINGS  (edit the values between the quotes)
# ============================================================
# DEMO MODE "1" = pretend to send (nothing is really sent)
# DEMO MODE "0" = really send, using the email / SMS details below

SETTINGS = {
    "FINDBACK_DEMO_MODE": "1",

    # Email (Gmail address + Gmail "App password", not your normal password)
    "FINDBACK_SMTP_USER": "",
    "FINDBACK_SMTP_PASSWORD": "",

    # SMS (Semaphore API key; leave empty if you don't have one)
    "FINDBACK_SMS_PROVIDER": "semaphore",
    "FINDBACK_SEMAPHORE_KEY": "",
    "FINDBACK_SEMAPHORE_SENDER": "",
}


# ============================================================
# FINDBACK - FUTURISTIC CAMPUS LOST & FOUND SYSTEM
# ============================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ============================================================
# COLORS
# ============================================================

BG = "#070B14"
SIDEBAR = "#0B1120"
CARD = "#101827"
CARD_HOVER = "#151F31"
BORDER = "#1E2B42"

BLUE = "#3B82F6"
CYAN = "#22D3EE"
PURPLE = "#8B5CF6"

WHITE = "#F8FAFC"
TEXT = "#CBD5E1"
MUTED = "#64748B"

GREEN = "#22C55E"
RED = "#F43F5E"


# ============================================================
# DATABASE
# ============================================================

DATABASE = "findback.db"
IMAGE_FOLDER = "findback_images"

ITEM_COLUMNS = """
    id, student_number, type, item, location,
    date, description, status, image_path
"""


def connect_database():
    return sqlite3.connect(DATABASE)


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def valid_date(text):
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def setup_database():

    connection = connect_database()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_number TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_number TEXT NOT NULL,
            type TEXT NOT NULL,
            item TEXT NOT NULL,
            location TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)

    # Add the image column safely for databases created by older versions.
    cursor.execute("PRAGMA table_info(items)")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if "image_path" not in existing_columns:
        cursor.execute("ALTER TABLE items ADD COLUMN image_path TEXT")

    # Add contact columns safely for databases created by older versions.
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row[1] for row in cursor.fetchall()]
    if "email" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "phone" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")

    os.makedirs(IMAGE_FOLDER, exist_ok=True)

    # Demo account (password is stored hashed)
    cursor.execute("""
        INSERT OR IGNORE INTO users
        (student_number, password, name)
        VALUES (?, ?, ?)
    """, (
        "123456",
        hash_password("1234"),
        "Charles Cruz"
    ))

    connection.commit()
    connection.close()


# ============================================================
# NOTIFICATION SETTINGS
# ============================================================
# Credentials are read from environment variables so they are
# never saved inside this file. Set them before running, e.g.
#   Windows (cmd):  setx FINDBACK_SMTP_USER "you@gmail.com"
#   macOS/Linux:    export FINDBACK_SMTP_USER="you@gmail.com"
#
# EMAIL (Gmail: turn on 2-step verification, then create an
# "App password" and use that as FINDBACK_SMTP_PASSWORD)
#   FINDBACK_SMTP_HOST      default smtp.gmail.com
#   FINDBACK_SMTP_PORT      default 587 (465 = SSL)
#   FINDBACK_SMTP_USER
#   FINDBACK_SMTP_PASSWORD
#   FINDBACK_SMTP_FROM      optional, defaults to the user
#
# SMS (choose a provider with FINDBACK_SMS_PROVIDER)
#   semaphore (default, Philippine provider)
#       FINDBACK_SEMAPHORE_KEY, FINDBACK_SEMAPHORE_SENDER (optional)
#   twilio
#       FINDBACK_TWILIO_SID, FINDBACK_TWILIO_TOKEN, FINDBACK_TWILIO_FROM

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "findback_settings.json"
)

SETTINGS_STATUS = (
    "Fill in the YOUR SETTINGS block at the top of the code, "
    "then restart the app."
)

# Optional: values in findback_settings.json (if the file exists) override the above
try:
    if os.path.isfile(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8-sig") as settings_file:
            for key, value in json.load(settings_file).items():
                if str(value).strip():
                    SETTINGS[key] = value
except Exception as error:
    SETTINGS_STATUS = f"findback_settings.json has a typo and was ignored: {error}"


def _env(name, default=""):
    """Read a setting from environment variables, then findback_settings.json."""
    value = os.environ.get(name) or SETTINGS.get(name) or default
    return str(value).strip()


def demo_mode():
    """When on, sending is simulated and nothing leaves the computer."""
    return _env("FINDBACK_DEMO_MODE", "0").lower() in ("1", "true", "yes", "on")


def email_is_configured():
    if demo_mode():
        return True
    return bool(_env("FINDBACK_SMTP_USER") and _env("FINDBACK_SMTP_PASSWORD"))


def sms_is_configured():
    if demo_mode():
        return True
    if _env("FINDBACK_SMS_PROVIDER", "semaphore").lower() == "twilio":
        return bool(
            _env("FINDBACK_TWILIO_SID")
            and _env("FINDBACK_TWILIO_TOKEN")
            and _env("FINDBACK_TWILIO_FROM")
        )
    return bool(_env("FINDBACK_SEMAPHORE_KEY"))


def is_valid_email(text):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text))


def normalize_phone(number):
    """Return a Philippine mobile number as +639XXXXXXXXX, or None."""
    digits = re.sub(r"[\s\-()]", "", number)

    if digits.startswith("+"):
        digits = digits[1:]

    if digits.startswith("09") and len(digits) == 11:
        digits = "63" + digits[1:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "63" + digits

    if re.fullmatch(r"63\d{10}", digits):
        return "+" + digits

    # Allow other international numbers (8-15 digits)
    if re.fullmatch(r"\d{8,15}", digits) and number.strip().startswith("+"):
        return "+" + digits

    return None


def send_email(to_address, subject, body):
    """Send a plain-text email. Raises an exception on failure."""
    if demo_mode():
        time.sleep(1)
        return

    host = _env("FINDBACK_SMTP_HOST", "smtp.gmail.com")
    port = int(_env("FINDBACK_SMTP_PORT", "587"))
    user = _env("FINDBACK_SMTP_USER")
    password = _env("FINDBACK_SMTP_PASSWORD")
    sender = _env("FINDBACK_SMTP_FROM", user) or user

    if not user or not password:
        raise RuntimeError(
            "Email is not configured. " + SETTINGS_STATUS
        )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(user, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(message)


def send_sms(phone_number, text):
    """Send an SMS through the configured provider. Raises on failure."""
    if demo_mode():
        time.sleep(1)
        return

    provider = _env("FINDBACK_SMS_PROVIDER", "semaphore").lower()

    if not sms_is_configured():
        raise RuntimeError(
            "SMS is not configured. " + SETTINGS_STATUS
        )

    if provider == "twilio":

        sid = _env("FINDBACK_TWILIO_SID")
        token = _env("FINDBACK_TWILIO_TOKEN")

        data = urllib.parse.urlencode({
            "To": phone_number,
            "From": _env("FINDBACK_TWILIO_FROM"),
            "Body": text
        }).encode("utf-8")

        request = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=data
        )

        credentials = base64.b64encode(
            f"{sid}:{token}".encode("utf-8")
        ).decode("ascii")

        request.add_header("Authorization", f"Basic {credentials}")

    else:

        fields = {
            "apikey": _env("FINDBACK_SEMAPHORE_KEY"),
            "number": phone_number.lstrip("+"),
            "message": text
        }

        sender_name = _env("FINDBACK_SEMAPHORE_SENDER")
        if sender_name:
            fields["sendername"] = sender_name

        request = urllib.request.Request(
            "https://api.semaphore.co/api/v4/messages",
            data=urllib.parse.urlencode(fields).encode("utf-8")
        )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"SMS provider error {error.code}: {detail}")


# ============================================================
# IMAGE MATCHING HELPERS
# ============================================================

MATCH_THRESHOLD = 65   # minimum similarity (%) to be listed as a possible match


def image_signature(image_path):
    """
    Build a signature for an image made of:
      - a 16x16 gradient hash (shape/structure, ignores brightness)
      - a 64-bin color histogram (overall colors)
    """
    if Image is None or not image_path or not os.path.isfile(image_path):
        return None

    try:
        with Image.open(image_path) as opened:
            # Fix rotated phone photos, then force RGB
            source = ImageOps.exif_transpose(opened).convert("RGB")

        gray = ImageOps.grayscale(source).resize((17, 16))
        pixels = gray.tobytes()

        bits = []
        for row in range(16):
            for col in range(16):
                index = row * 17 + col
                bits.append(1 if pixels[index] > pixels[index + 1] else 0)

        small = source.resize((64, 64)).tobytes()
        histogram = [0] * 64

        for i in range(0, len(small), 3):
            bin_index = (
                (small[i] // 64) * 16
                + (small[i + 1] // 64) * 4
                + (small[i + 2] // 64)
            )
            histogram[bin_index] += 1

        total = sum(histogram)
        histogram = [count / total for count in histogram]

        return tuple(bits), histogram

    except Exception:
        return None


def image_similarity(first, second):
    """Return a 0-100 similarity score, or None if either image failed."""
    if first is None or second is None:
        return None

    first_bits, first_hist = first
    second_bits, second_hist = second

    different = sum(a != b for a, b in zip(first_bits, second_bits))
    shape_score = 1 - different / len(first_bits)

    color_score = sum(
        min(a, b) for a, b in zip(first_hist, second_hist)
    )

    return round((0.6 * shape_score + 0.4 * color_score) * 100)


def save_image_copy(source_path, student_number):
    """Copy an image into IMAGE_FOLDER and return the new path."""
    os.makedirs(IMAGE_FOLDER, exist_ok=True)

    extension = os.path.splitext(source_path)[1].lower()
    filename = (
        f"{student_number}_"
        f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        f"{extension}"
    )
    destination = os.path.join(IMAGE_FOLDER, filename)
    shutil.copy2(source_path, destination)
    return destination


# ============================================================
# LOGIN WINDOW
# ============================================================

class LoginWindow(ctk.CTk):

    def __init__(self):

        super().__init__()

        self.user = None   # set to (student_number, name) on successful login

        self.title("FindBack — Login")
        self.geometry("1000x650")
        self.minsize(850, 550)

        self.configure(fg_color=BG)

        self.create_login()


    def create_login(self):

        # LEFT PANEL

        left = ctk.CTkFrame(
            self,
            width=430,
            corner_radius=0,
            fg_color="#090F1D"
        )

        left.pack(side="left", fill="both")
        left.pack_propagate(False)

        ctk.CTkLabel(
            left,
            text="◈",
            font=ctk.CTkFont(size=70, weight="bold"),
            text_color=CYAN
        ).pack(pady=(120, 10))

        ctk.CTkLabel(
            left,
            text="FINDBACK",
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=WHITE
        ).pack()

        ctk.CTkLabel(
            left,
            text="CAMPUS LOST & FOUND",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=CYAN
        ).pack(pady=(5, 20))

        ctk.CTkLabel(
            left,
            text="Reconnect people with their\nlost belongings.",
            font=ctk.CTkFont(size=14),
            text_color=MUTED,
            justify="center"
        ).pack()

        ctk.CTkLabel(
            left,
            text="●  SYSTEM ONLINE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=GREEN
        ).pack(side="bottom", pady=35)

        # RIGHT PANEL

        right = ctk.CTkFrame(
            self,
            fg_color=BG,
            corner_radius=0
        )

        right.pack(side="right", fill="both", expand=True)

        login_card = ctk.CTkFrame(
            right,
            width=400,
            fg_color=CARD,
            corner_radius=20,
            border_width=1,
            border_color=BORDER
        )

        login_card.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            login_card,
            text="Welcome back",
            font=ctk.CTkFont(size=25, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w", padx=35, pady=(35, 5))

        ctk.CTkLabel(
            login_card,
            text="Sign in to your student account",
            font=ctk.CTkFont(size=11),
            text_color=MUTED
        ).pack(anchor="w", padx=35, pady=(0, 25))

        ctk.CTkLabel(
            login_card,
            text="STUDENT NUMBER",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=MUTED
        ).pack(anchor="w", padx=35, pady=(0, 7))

        self.student_entry = ctk.CTkEntry(
            login_card,
            placeholder_text="Enter your student number",
            width=330,
            height=45,
            corner_radius=10,
            fg_color="#0D1525",
            border_color=BORDER
        )

        self.student_entry.pack(padx=35)

        ctk.CTkLabel(
            login_card,
            text="PASSWORD",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=MUTED
        ).pack(anchor="w", padx=35, pady=(20, 7))

        self.password_entry = ctk.CTkEntry(
            login_card,
            placeholder_text="Enter your password",
            show="●",
            width=330,
            height=45,
            corner_radius=10,
            fg_color="#0D1525",
            border_color=BORDER
        )

        self.password_entry.pack(padx=35)

        ctk.CTkButton(
            login_card,
            text="SIGN IN  →",
            width=330,
            height=47,
            corner_radius=10,
            fg_color=BLUE,
            hover_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.login
        ).pack(padx=35, pady=(25, 10))

        ctk.CTkButton(
            login_card,
            text="CREATE STUDENT ACCOUNT",
            width=330,
            height=40,
            corner_radius=10,
            fg_color="transparent",
            hover_color=CARD_HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=CYAN,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.open_register
        ).pack(padx=35, pady=(0, 12))

        ctk.CTkLabel(
            login_card,
            text="Demo account: 123456  /  1234",
            font=ctk.CTkFont(size=10),
            text_color=MUTED
        ).pack(pady=(0, 25))

        self.password_entry.bind(
            "<Return>",
            lambda event: self.login()
        )


    # ========================================================
    # LOGIN
    # ========================================================

    def login(self):

        student_number = self.student_entry.get().strip()
        password = self.password_entry.get().strip()

        if not student_number or not password:
            messagebox.showwarning(
                "Missing Information",
                "Please enter your student number and password."
            )
            return

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT name, password
            FROM users
            WHERE student_number = ?
        """, (student_number,))

        row = cursor.fetchone()

        user = None

        if row:
            name, stored = row

            if stored == hash_password(password):
                user = name

            elif stored == password:
                # Old plain-text account: log in and upgrade to a hash.
                user = name
                cursor.execute("""
                    UPDATE users
                    SET password = ?
                    WHERE student_number = ?
                """, (hash_password(password), student_number))
                connection.commit()

        connection.close()

        if user:
            self.user = (student_number, user)
            self.destroy()
        else:
            messagebox.showerror(
                "Login Failed",
                "Invalid student number or password."
            )


    # ========================================================
    # REGISTER
    # ========================================================

    def open_register(self):

        register_window = ctk.CTkToplevel(self)
        register_window.title("FindBack — Create Account")
        register_window.geometry("500x800")
        register_window.configure(fg_color=BG)
        register_window.after(100, register_window.grab_set)

        card = ctk.CTkFrame(
            register_window,
            fg_color=CARD,
            corner_radius=20,
            border_width=1,
            border_color=BORDER
        )

        card.pack(fill="both", expand=True, padx=25, pady=25)

        ctk.CTkLabel(
            card,
            text="Create Student Account",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w", padx=30, pady=(30, 5))

        ctk.CTkLabel(
            card,
            text="Register your campus FindBack account.",
            font=ctk.CTkFont(size=11),
            text_color=MUTED
        ).pack(anchor="w", padx=30, pady=(0, 25))

        def make_field(label, placeholder, show=None, last=False):
            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=MUTED
            ).pack(anchor="w", padx=30)

            entry = ctk.CTkEntry(
                card,
                placeholder_text=placeholder,
                show=show,
                width=400,
                height=42,
                corner_radius=10,
                fg_color="#0D1525",
                border_color=BORDER
            )
            entry.pack(padx=30, pady=(7, 22 if last else 12))
            return entry

        name_entry = make_field("FULL NAME", "Enter your full name")
        student_entry = make_field("STUDENT NUMBER", "Enter your student number")
        email_entry = make_field("EMAIL (OPTIONAL)", "name@example.com")
        phone_entry = make_field("MOBILE NUMBER (OPTIONAL)", "09XXXXXXXXX")
        password_entry = make_field("PASSWORD", "Create a password", show="●")
        confirm_entry = make_field(
            "CONFIRM PASSWORD", "Confirm your password", show="●", last=True
        )

        def register():

            name = name_entry.get().strip()
            student_number = student_entry.get().strip()
            password = password_entry.get().strip()
            confirm_password = confirm_entry.get().strip()
            email = email_entry.get().strip()
            phone = phone_entry.get().strip()

            if not name or not student_number or not password:
                messagebox.showwarning(
                    "Missing Information",
                    "Please complete all fields."
                )
                return

            if password != confirm_password:
                messagebox.showerror(
                    "Password Error",
                    "Passwords do not match."
                )
                return

            if email and not is_valid_email(email):
                messagebox.showerror(
                    "Invalid Email",
                    "Please enter a valid email address."
                )
                return

            if phone:
                phone = normalize_phone(phone)
                if not phone:
                    messagebox.showerror(
                        "Invalid Number",
                        "Enter a mobile number like 09171234567 "
                        "or +639171234567."
                    )
                    return

            connection = connect_database()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT id
                FROM users
                WHERE student_number = ?
            """, (student_number,))

            if cursor.fetchone():
                connection.close()
                messagebox.showerror(
                    "Registration Failed",
                    "That student number is already registered."
                )
                return

            cursor.execute("""
                INSERT INTO users (student_number, password, name, email, phone)
                VALUES (?, ?, ?, ?, ?)
            """, (
                student_number,
                hash_password(password),
                name,
                email or None,
                phone or None
            ))

            connection.commit()
            connection.close()

            messagebox.showinfo(
                "Account Created",
                "Student account created successfully."
            )

            register_window.destroy()

        ctk.CTkButton(
            card,
            text="CREATE ACCOUNT",
            width=200,
            height=45,
            corner_radius=10,
            fg_color=BLUE,
            hover_color="#2563EB",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=register
        ).pack()


# ============================================================
# MAIN APPLICATION
# ============================================================

class FindBackApp(ctk.CTk):

    def __init__(self, student_number, student_name):

        super().__init__()

        self.student_number = student_number
        self.student_name = student_name
        self.logged_out = False

        self.current_page = "dashboard"
        self.active_filter = "All"

        self.title("FindBack — Campus Lost & Found")
        self.geometry("1280x760")
        self.minsize(1100, 680)
        self.configure(fg_color=BG)

        self.create_sidebar()
        self.create_main_area()

        self.show_dashboard()


    # ========================================================
    # SIDEBAR
    # ========================================================

    def create_sidebar(self):

        self.sidebar = ctk.CTkFrame(
            self,
            width=245,
            corner_radius=0,
            fg_color=SIDEBAR
        )

        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(padx=25, pady=(30, 35), fill="x")

        ctk.CTkLabel(
            logo_frame,
            text="◈",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=CYAN
        ).pack(side="left")

        ctk.CTkLabel(
            logo_frame,
            text="  FINDBACK",
            font=ctk.CTkFont(size=21, weight="bold"),
            text_color=WHITE
        ).pack(side="left")

        ctk.CTkLabel(
            self.sidebar,
            text="MAIN MENU",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=MUTED
        ).pack(anchor="w", padx=28, pady=(0, 10))

        self.create_nav_button("⌂   Dashboard", self.show_dashboard)
        self.create_nav_button("＋   Report Item", self.show_report)
        self.create_nav_button("▣   All Reports", self.show_records)
        self.create_nav_button("⌕   Search", self.show_search)
        self.create_nav_button("◈   Image Matching", self.show_image_matching)

        spacer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        spacer.pack(expand=True, fill="both")

        status_card = ctk.CTkFrame(
            self.sidebar,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        status_card.pack(padx=18, pady=(0, 15), fill="x")

        ctk.CTkLabel(
            status_card,
            text="SYSTEM STATUS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=MUTED
        ).pack(anchor="w", padx=15, pady=(14, 4))

        ctk.CTkLabel(
            status_card,
            text="●  DATABASE ONLINE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=GREEN
        ).pack(anchor="w", padx=15, pady=(0, 14))

        user_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        user_frame.pack(padx=20, pady=(0, 25), fill="x")

        avatar = ctk.CTkFrame(
            user_frame,
            width=38,
            height=38,
            corner_radius=12,
            fg_color=BLUE
        )

        avatar.pack(side="left")
        avatar.pack_propagate(False)

        ctk.CTkLabel(
            avatar,
            text=self.student_name[:1].upper(),
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=WHITE
        ).pack(expand=True)

        user_info = ctk.CTkFrame(user_frame, fg_color="transparent")

        ctk.CTkLabel(
            user_info,
            text=self.student_name,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w")

        ctk.CTkLabel(
            user_info,
            text=self.student_number,
            font=ctk.CTkFont(size=9),
            text_color=MUTED
        ).pack(anchor="w")

        user_info.pack(side="left", padx=10)

        ctk.CTkButton(
            self.sidebar,
            text="LOG OUT",
            height=38,
            corner_radius=9,
            fg_color="transparent",
            hover_color=CARD_HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=RED,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.logout
        ).pack(padx=18, pady=(0, 20), fill="x")


    # ========================================================
    # NAVIGATION BUTTON
    # ========================================================

    def create_nav_button(self, text, command):

        button = ctk.CTkButton(
            self.sidebar,
            text=text,
            height=45,
            corner_radius=10,
            fg_color="transparent",
            hover_color=CARD_HOVER,
            text_color=TEXT,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=command
        )

        button.pack(padx=18, pady=4, fill="x")


    # ========================================================
    # MAIN AREA
    # ========================================================

    def create_main_area(self):

        self.main_area = ctk.CTkFrame(
            self,
            fg_color=BG,
            corner_radius=0
        )

        self.main_area.pack(side="right", fill="both", expand=True)


    def clear_main_area(self):

        for widget in self.main_area.winfo_children():
            widget.destroy()


    def refresh_view(self):
        """Reload whichever page the user is currently on."""
        if self.current_page == "records":
            self.filter_records(self.active_filter)
        elif self.current_page == "search":
            self.perform_search()
        else:
            self.show_dashboard()


    # ========================================================
    # PAGE HEADER
    # ========================================================

    def create_page_header(self, title, subtitle):

        header = ctk.CTkFrame(self.main_area, fg_color="transparent")
        header.pack(fill="x", padx=35, pady=(30, 20))

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=27, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text=subtitle,
            font=ctk.CTkFont(size=12),
            text_color=MUTED
        ).pack(anchor="w", pady=(5, 0))


    # ========================================================
    # DATABASE STATISTICS
    # ========================================================

    def get_statistics(self):

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM items")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM items WHERE type = 'Lost'")
        lost = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM items WHERE type = 'Found'")
        found = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM items WHERE status = 'Claimed'")
        claimed = cursor.fetchone()[0]

        connection.close()

        return total, lost, found, claimed


    # ========================================================
    # DASHBOARD
    # ========================================================

    def show_dashboard(self):

        self.current_page = "dashboard"
        self.clear_main_area()

        self.create_page_header(
            "Dashboard",
            "Campus lost and found overview"
        )

        total, lost, found, claimed = self.get_statistics()

        stats_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        stats_frame.pack(fill="x", padx=35, pady=(0, 25))

        stats = [
            ("TOTAL REPORTS", total, BLUE),
            ("LOST ITEMS", lost, RED),
            ("FOUND ITEMS", found, CYAN),
            ("CLAIMED ITEMS", claimed, GREEN)
        ]

        for title, value, color in stats:

            card = ctk.CTkFrame(
                stats_frame,
                fg_color=CARD,
                corner_radius=15,
                border_width=1,
                border_color=BORDER
            )

            card.pack(side="left", expand=True, fill="both", padx=6)

            ctk.CTkLabel(
                card,
                text=title,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=MUTED
            ).pack(anchor="w", padx=18, pady=(18, 5))

            ctk.CTkLabel(
                card,
                text=str(value),
                font=ctk.CTkFont(size=30, weight="bold"),
                text_color=color
            ).pack(anchor="w", padx=18, pady=(0, 18))

        self.create_recent_reports()


    # ========================================================
    # RECENT REPORTS
    # ========================================================

    def create_recent_reports(self):

        ctk.CTkLabel(
            self.main_area,
            text="Recent Reports",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w", padx=35, pady=(5, 15))

        # Scrollable so the list never overflows a small window
        recent_container = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent"
        )

        recent_container.pack(fill="both", expand=True, pady=(0, 20))

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute(f"""
            SELECT {ITEM_COLUMNS}
            FROM items
            ORDER BY id DESC
            LIMIT 5
        """)

        items = cursor.fetchall()

        connection.close()

        if not items:
            self.show_empty_state(
                recent_container,
                "No reports yet",
                "Lost and found reports will appear here."
            )
            return

        for item in items:
            self.create_record_card(recent_container, item, compact=True)


    # ========================================================
    # EMPTY STATE
    # ========================================================

    def show_empty_state(self, parent, title, subtitle):

        empty = ctk.CTkFrame(
            parent,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        empty.pack(fill="x", padx=35, pady=15)

        ctk.CTkLabel(
            empty,
            text="◈",
            font=ctk.CTkFont(size=35),
            text_color=MUTED
        ).pack(pady=(25, 5))

        ctk.CTkLabel(
            empty,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=WHITE
        ).pack()

        ctk.CTkLabel(
            empty,
            text=subtitle,
            font=ctk.CTkFont(size=11),
            text_color=MUTED
        ).pack(pady=(5, 25))


    # ========================================================
    # RECORD CARD
    # ========================================================

    def create_record_card(self, parent, item, compact=False):

        (
            item_id,
            owner,
            item_type,
            item_name,
            location,
            date,
            description,
            status,
            image_path
        ) = item

        color = RED if item_type == "Lost" else CYAN

        card = ctk.CTkFrame(
            parent,
            fg_color=CARD,
            corner_radius=14,
            border_width=1,
            border_color=BORDER
        )

        card.pack(fill="x", padx=35, pady=6)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(15, 5))

        ctk.CTkLabel(
            top,
            text=item_type.upper(),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=color
        ).pack(side="left")

        ctk.CTkLabel(
            top,
            text=status.upper(),
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=GREEN if status == "Claimed" else MUTED
        ).pack(side="right")

        ctk.CTkLabel(
            card,
            text=item_name,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w", padx=18, pady=(5, 2))

        ctk.CTkLabel(
            card,
            text=f"Location: {location}    Date: {date}",
            font=ctk.CTkFont(size=10),
            text_color=MUTED
        ).pack(anchor="w", padx=18, pady=(0, 8))

        if not compact:

            ctk.CTkLabel(
                card,
                text=description,
                font=ctk.CTkFont(size=11),
                text_color=TEXT,
                wraplength=750,
                justify="left"
            ).pack(anchor="w", padx=18, pady=(0, 10))

        if image_path and os.path.isfile(image_path) and Image is not None:

            try:
                with Image.open(image_path) as opened:
                    source_image = opened.copy()

                source_image.thumbnail((180, 130))

                preview = ctk.CTkImage(
                    light_image=source_image,
                    dark_image=source_image,
                    size=(source_image.width, source_image.height)
                )

                ctk.CTkLabel(
                    card,
                    text="",
                    image=preview
                ).pack(anchor="w", padx=18, pady=(0, 10))

            except Exception:
                pass

        if owner == self.student_number:

            actions = ctk.CTkFrame(card, fg_color="transparent")
            actions.pack(anchor="e", padx=15, pady=(0, 12))

            ctk.CTkButton(
                actions,
                text="EDIT",
                width=75,
                height=28,
                fg_color=BLUE,
                hover_color="#2563EB",
                command=lambda i=item_id: self.edit_item(i)
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                actions,
                text="DELETE",
                width=75,
                height=28,
                fg_color=RED,
                hover_color="#BE123C",
                command=lambda i=item_id: self.delete_item(i)
            ).pack(side="left", padx=4)

            if status != "Claimed":

                ctk.CTkButton(
                    actions,
                    text="MARK CLAIMED",
                    width=120,
                    height=28,
                    fg_color=GREEN,
                    hover_color="#16A34A",
                    command=lambda i=item_id: self.mark_claimed(i)
                ).pack(side="left", padx=4)


    # ========================================================
    # REPORT ITEM PAGE
    # ========================================================

    def show_report(self):

        self.current_page = "report"
        self.clear_main_area()

        self.create_page_header(
            "Report an Item",
            "Submit a lost or found item report."
        )

        form = ctk.CTkFrame(
            self.main_area,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color=BORDER
        )

        form.pack(fill="both", expand=True, padx=35, pady=(0, 25))
        form.grid_columnconfigure(1, weight=1)

        self.report_type = ctk.StringVar(value="Lost")
        self.report_image_path = None

        label_font = ctk.CTkFont(size=10, weight="bold")

        ctk.CTkLabel(
            form, text="REPORT TYPE", text_color=MUTED, font=label_font
        ).grid(row=0, column=0, padx=25, pady=(25, 8), sticky="w")

        type_frame = ctk.CTkFrame(form, fg_color="transparent")
        type_frame.grid(row=0, column=1, padx=20, pady=(20, 5), sticky="w")

        ctk.CTkRadioButton(
            type_frame,
            text="Lost Item",
            variable=self.report_type,
            value="Lost",
            text_color=WHITE,
            fg_color=BLUE
        ).pack(side="left", padx=(0, 25))

        ctk.CTkRadioButton(
            type_frame,
            text="Found Item",
            variable=self.report_type,
            value="Found",
            text_color=WHITE,
            fg_color=CYAN
        ).pack(side="left")

        ctk.CTkLabel(
            form, text="ITEM NAME", text_color=MUTED, font=label_font
        ).grid(row=1, column=0, padx=25, pady=12, sticky="w")

        self.report_item_entry = ctk.CTkEntry(
            form,
            placeholder_text="Example: Black wallet",
            height=42,
            fg_color="#0D1525",
            border_color=BORDER
        )

        self.report_item_entry.grid(
            row=1, column=1, padx=20, pady=10, sticky="ew"
        )

        ctk.CTkLabel(
            form, text="LOCATION", text_color=MUTED, font=label_font
        ).grid(row=2, column=0, padx=25, pady=12, sticky="w")

        self.report_location_entry = ctk.CTkEntry(
            form,
            placeholder_text="Where was it lost or found?",
            height=42,
            fg_color="#0D1525",
            border_color=BORDER
        )

        self.report_location_entry.grid(
            row=2, column=1, padx=20, pady=10, sticky="ew"
        )

        ctk.CTkLabel(
            form, text="DATE (YYYY-MM-DD)", text_color=MUTED, font=label_font
        ).grid(row=3, column=0, padx=25, pady=12, sticky="w")

        self.report_date_entry = ctk.CTkEntry(
            form,
            height=42,
            fg_color="#0D1525",
            border_color=BORDER
        )

        self.report_date_entry.grid(
            row=3, column=1, padx=20, pady=10, sticky="ew"
        )

        self.report_date_entry.insert(
            0, datetime.now().strftime("%Y-%m-%d")
        )

        ctk.CTkLabel(
            form, text="DESCRIPTION", text_color=MUTED, font=label_font
        ).grid(row=4, column=0, padx=25, pady=12, sticky="nw")

        self.report_description = ctk.CTkTextbox(
            form,
            height=115,
            fg_color="#0D1525",
            border_color=BORDER,
            border_width=1,
            corner_radius=10,
            text_color=WHITE
        )

        self.report_description.grid(
            row=4, column=1, padx=20, pady=10, sticky="ew"
        )

        ctk.CTkLabel(
            form, text="ITEM IMAGE", text_color=MUTED, font=label_font
        ).grid(row=5, column=0, padx=25, pady=12, sticky="w")

        image_frame = ctk.CTkFrame(form, fg_color="transparent")
        image_frame.grid(row=5, column=1, padx=20, pady=10, sticky="w")

        self.report_image_label = ctk.CTkLabel(
            image_frame,
            text="No image selected",
            text_color=MUTED
        )

        self.report_image_label.pack(side="left", padx=(0, 15))

        ctk.CTkButton(
            image_frame,
            text="UPLOAD IMAGE",
            width=140,
            height=35,
            fg_color=PURPLE,
            hover_color="#7C3AED",
            command=self.select_report_image
        ).pack(side="left")

        ctk.CTkButton(
            form,
            text="SUBMIT REPORT",
            width=190,
            height=45,
            fg_color=BLUE,
            hover_color="#2563EB",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.submit_report
        ).grid(row=6, column=1, padx=20, pady=25, sticky="w")


    # ========================================================
    # SELECT REPORT IMAGE
    # ========================================================

    def select_report_image(self):

        path = filedialog.askopenfilename(
            title="Select Item Image",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.webp"),
                ("All Files", "*.*")
            ]
        )

        if not path:
            return

        self.report_image_path = path

        self.report_image_label.configure(
            text=os.path.basename(path),
            text_color=CYAN
        )


    # ========================================================
    # SAVE REPORT
    # ========================================================

    def submit_report(self):

        item_type = self.report_type.get()
        item_name = self.report_item_entry.get().strip()
        location = self.report_location_entry.get().strip()
        date = self.report_date_entry.get().strip()
        description = self.report_description.get("1.0", "end").strip()

        if not item_name or not location or not date or not description:
            messagebox.showwarning(
                "Missing Information",
                "Please complete all required fields."
            )
            return

        if not valid_date(date):
            messagebox.showwarning(
                "Invalid Date",
                "Please enter the date as YYYY-MM-DD (for example 2026-11-03)."
            )
            return

        image_path = None

        if self.report_image_path:
            try:
                image_path = save_image_copy(
                    self.report_image_path,
                    self.student_number
                )
            except Exception as error:
                messagebox.showerror(
                    "Image Error",
                    f"Could not save image:\n{error}"
                )
                return

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO items (
                student_number, type, item, location,
                date, description, status, image_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.student_number,
            item_type,
            item_name,
            location,
            date,
            description,
            "Active",
            image_path
        ))

        connection.commit()
        connection.close()

        messagebox.showinfo(
            "Report Submitted",
            "Your item report was submitted successfully."
        )

        self.show_dashboard()


    # ========================================================
    # FETCH REPORTS
    # ========================================================

    def fetch_items(self, search_text=""):

        connection = connect_database()
        cursor = connection.cursor()

        if search_text:

            keyword = f"%{search_text}%"

            cursor.execute(f"""
                SELECT {ITEM_COLUMNS}
                FROM items
                WHERE
                    item LIKE ?
                    OR location LIKE ?
                    OR description LIKE ?
                    OR type LIKE ?
                    OR status LIKE ?
                ORDER BY id DESC
            """, (keyword, keyword, keyword, keyword, keyword))

        else:

            cursor.execute(f"""
                SELECT {ITEM_COLUMNS}
                FROM items
                ORDER BY id DESC
            """)

        results = cursor.fetchall()

        connection.close()

        return results


    # ========================================================
    # ALL RECORDS
    # ========================================================

    def show_records(self):

        self.current_page = "records"
        self.active_filter = "All"
        self.clear_main_area()

        self.create_page_header(
            "All Reports",
            "Browse campus lost and found records."
        )

        filter_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        filter_frame.pack(fill="x", padx=35, pady=(0, 15))

        for option in ["All", "Lost", "Found", "Claimed"]:

            ctk.CTkButton(
                filter_frame,
                text=option,
                width=100,
                height=35,
                fg_color=CARD,
                hover_color=CARD_HOVER,
                border_width=1,
                border_color=BORDER,
                command=lambda value=option: self.filter_records(value)
            ).pack(side="left", padx=(0, 8))

        self.records_container = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent"
        )

        self.records_container.pack(
            fill="both", expand=True, padx=0, pady=(0, 20)
        )

        self.filter_records("All")


    def filter_records(self, selected_filter):

        if not hasattr(self, "records_container"):
            return

        self.active_filter = selected_filter

        for widget in self.records_container.winfo_children():
            widget.destroy()

        items = self.fetch_items()

        if selected_filter == "Lost":
            items = [i for i in items if i[2] == "Lost"]
        elif selected_filter == "Found":
            items = [i for i in items if i[2] == "Found"]
        elif selected_filter == "Claimed":
            items = [i for i in items if i[7] == "Claimed"]

        if not items:
            self.show_empty_state(
                self.records_container,
                "No matching reports",
                "Try selecting another filter."
            )
            return

        for item in items:
            self.create_record_card(self.records_container, item)


    # ========================================================
    # SEARCH PAGE
    # ========================================================

    def show_search(self):

        self.current_page = "search"
        self.clear_main_area()

        self.create_page_header(
            "Search Reports",
            "Find items by name, location, description, or status."
        )

        search_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        search_frame.pack(fill="x", padx=35, pady=(0, 20))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search for an item or location...",
            height=45,
            fg_color=CARD,
            border_color=BORDER
        )

        self.search_entry.pack(
            side="left", fill="x", expand=True, padx=(0, 10)
        )

        ctk.CTkButton(
            search_frame,
            text="SEARCH",
            width=120,
            height=45,
            fg_color=BLUE,
            hover_color="#2563EB",
            command=self.perform_search
        ).pack(side="right")

        self.search_entry.bind(
            "<Return>",
            lambda event: self.perform_search()
        )

        self.search_results = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent"
        )

        self.search_results.pack(fill="both", expand=True)

        self.perform_search()


    def perform_search(self):

        if not hasattr(self, "search_results"):
            return

        for widget in self.search_results.winfo_children():
            widget.destroy()

        keyword = self.search_entry.get().strip()

        results = self.fetch_items(keyword)

        if not results:
            self.show_empty_state(
                self.search_results,
                "No results found",
                "Try another item name or location."
            )
            return

        for item in results:
            self.create_record_card(self.search_results, item)


    # ========================================================
    # EDIT REPORT
    # ========================================================

    def edit_item(self, item_id):

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute(f"""
            SELECT {ITEM_COLUMNS}
            FROM items
            WHERE id = ?
        """, (item_id,))

        item = cursor.fetchone()

        connection.close()

        if not item:
            messagebox.showerror(
                "Not Found",
                "This report no longer exists."
            )
            return

        if item[1] != self.student_number:
            messagebox.showerror(
                "Access Denied",
                "You can only edit your own reports."
            )
            return

        old_image_path = item[8]
        new_image = {"path": None}

        window = ctk.CTkToplevel(self)
        window.title("Edit Report")
        window.geometry("550x720")
        window.configure(fg_color=BG)
        window.after(100, window.grab_set)

        card = ctk.CTkFrame(window, fg_color=CARD, corner_radius=15)
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            card,
            text="EDIT ITEM REPORT",
            font=ctk.CTkFont(size=21, weight="bold"),
            text_color=WHITE
        ).pack(anchor="w", padx=25, pady=(25, 20))

        ctk.CTkLabel(card, text="ITEM NAME", text_color=MUTED).pack(
            anchor="w", padx=25
        )

        name_entry = ctk.CTkEntry(
            card, height=40, fg_color="#0D1525", border_color=BORDER
        )
        name_entry.pack(fill="x", padx=25, pady=(5, 15))
        name_entry.insert(0, item[3])

        ctk.CTkLabel(card, text="LOCATION", text_color=MUTED).pack(
            anchor="w", padx=25
        )

        location_entry = ctk.CTkEntry(
            card, height=40, fg_color="#0D1525", border_color=BORDER
        )
        location_entry.pack(fill="x", padx=25, pady=(5, 15))
        location_entry.insert(0, item[4])

        ctk.CTkLabel(card, text="DATE (YYYY-MM-DD)", text_color=MUTED).pack(
            anchor="w", padx=25
        )

        date_entry = ctk.CTkEntry(
            card, height=40, fg_color="#0D1525", border_color=BORDER
        )
        date_entry.pack(fill="x", padx=25, pady=(5, 15))
        date_entry.insert(0, item[5])

        ctk.CTkLabel(card, text="DESCRIPTION", text_color=MUTED).pack(
            anchor="w", padx=25
        )

        description_box = ctk.CTkTextbox(
            card,
            height=130,
            fg_color="#0D1525",
            border_color=BORDER,
            border_width=1
        )
        description_box.pack(fill="x", padx=25, pady=(5, 15))
        description_box.insert("1.0", item[6])

        ctk.CTkLabel(card, text="ITEM IMAGE", text_color=MUTED).pack(
            anchor="w", padx=25
        )

        image_row = ctk.CTkFrame(card, fg_color="transparent")
        image_row.pack(fill="x", padx=25, pady=(5, 20))

        image_label = ctk.CTkLabel(
            image_row,
            text=(
                os.path.basename(old_image_path)
                if old_image_path else "No image"
            ),
            text_color=MUTED
        )
        image_label.pack(side="left", padx=(0, 15))

        def choose_new_image():
            path = filedialog.askopenfilename(
                title="Select Item Image",
                filetypes=[
                    ("Image Files", "*.png *.jpg *.jpeg *.webp"),
                    ("All Files", "*.*")
                ]
            )
            if path:
                new_image["path"] = path
                image_label.configure(
                    text=os.path.basename(path),
                    text_color=CYAN
                )

        ctk.CTkButton(
            image_row,
            text="CHANGE IMAGE",
            width=130,
            height=32,
            fg_color=PURPLE,
            hover_color="#7C3AED",
            command=choose_new_image
        ).pack(side="left")

        def save_changes():

            name = name_entry.get().strip()
            location = location_entry.get().strip()
            date = date_entry.get().strip()
            description = description_box.get("1.0", "end").strip()

            if not name or not location or not date or not description:
                messagebox.showwarning(
                    "Missing Information",
                    "Please complete all fields."
                )
                return

            if not valid_date(date):
                messagebox.showwarning(
                    "Invalid Date",
                    "Please enter the date as YYYY-MM-DD."
                )
                return

            image_path = old_image_path

            if new_image["path"]:
                try:
                    image_path = save_image_copy(
                        new_image["path"],
                        self.student_number
                    )
                except Exception as error:
                    messagebox.showerror(
                        "Image Error",
                        f"Could not save image:\n{error}"
                    )
                    return

            connection = connect_database()
            cursor = connection.cursor()

            cursor.execute("""
                UPDATE items
                SET
                    item = ?,
                    location = ?,
                    date = ?,
                    description = ?,
                    image_path = ?
                WHERE
                    id = ?
                    AND student_number = ?
            """, (
                name,
                location,
                date,
                description,
                image_path,
                item_id,
                self.student_number
            ))

            connection.commit()
            connection.close()

            # Remove the old image file if it was replaced
            if (
                new_image["path"]
                and old_image_path
                and os.path.isfile(old_image_path)
            ):
                try:
                    os.remove(old_image_path)
                except OSError:
                    pass

            window.destroy()

            messagebox.showinfo(
                "Updated",
                "Your report was updated successfully."
            )

            self.refresh_view()

        ctk.CTkButton(
            card,
            text="SAVE CHANGES",
            height=43,
            fg_color=BLUE,
            hover_color="#2563EB",
            command=save_changes
        ).pack(padx=25, pady=(0, 25), fill="x")


    # ========================================================
    # DELETE REPORT
    # ========================================================

    def delete_item(self, item_id):

        confirm = messagebox.askyesno(
            "Delete Report",
            "Are you sure you want to delete this report?"
        )

        if not confirm:
            return

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT image_path
            FROM items
            WHERE id = ?
            AND student_number = ?
        """, (item_id, self.student_number))

        result = cursor.fetchone()

        if not result:
            connection.close()
            messagebox.showerror(
                "Access Denied",
                "You can only delete your own reports."
            )
            return

        image_path = result[0]

        cursor.execute("""
            DELETE FROM items
            WHERE id = ?
            AND student_number = ?
        """, (item_id, self.student_number))

        connection.commit()
        connection.close()

        if image_path and os.path.isfile(image_path):
            try:
                os.remove(image_path)
            except OSError:
                pass

        messagebox.showinfo("Deleted", "Report deleted successfully.")

        self.refresh_view()


    # ========================================================
    # MARK ITEM AS CLAIMED
    # ========================================================

    def mark_claimed(self, item_id):

        confirm = messagebox.askyesno(
            "Mark as Claimed",
            "Are you sure this item has been claimed?"
        )

        if not confirm:
            return

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE items
            SET status = 'Claimed'
            WHERE id = ?
            AND student_number = ?
        """, (item_id, self.student_number))

        connection.commit()
        connection.close()

        messagebox.showinfo("Status Updated", "Item marked as claimed.")

        self.refresh_view()


    # ========================================================
    # IMAGE MATCHING PAGE
    # ========================================================

    def show_image_matching(self):

        self.current_page = "matching"
        self.clear_main_area()

        self.create_page_header(
            "Image Matching",
            "Compare a Lost item image with Found item images."
        )

        description = ctk.CTkFrame(
            self.main_area,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        description.pack(fill="x", padx=35, pady=(0, 15))

        ctk.CTkLabel(
            description,
            text="◈  VISUAL ITEM COMPARISON",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=CYAN
        ).pack(anchor="w", padx=20, pady=(18, 5))

        ctk.CTkLabel(
            description,
            text=(
                "Select an item image to compare it against reports "
                "of the opposite type. The system uses a simple "
                "image similarity estimate."
            ),
            font=ctk.CTkFont(size=11),
            text_color=MUTED,
            wraplength=850,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 18))

        controls = ctk.CTkFrame(self.main_area, fg_color="transparent")
        controls.pack(fill="x", padx=35, pady=10)

        self.match_image_path = None
        self.match_type = ctk.StringVar(value="Lost")

        ctk.CTkLabel(
            controls,
            text="Compare as:",
            text_color=TEXT
        ).pack(side="left", padx=(0, 10))

        ctk.CTkOptionMenu(
            controls,
            values=["Lost", "Found"],
            variable=self.match_type,
            fg_color=CARD,
            button_color=BLUE,
            button_hover_color="#2563EB"
        ).pack(side="left", padx=(0, 15))

        ctk.CTkButton(
            controls,
            text="SELECT IMAGE",
            width=130,
            height=38,
            fg_color=PURPLE,
            hover_color="#7C3AED",
            command=self.select_match_image
        ).pack(side="left", padx=5)

        self.match_image_label = ctk.CTkLabel(
            controls,
            text="No image selected",
            text_color=MUTED
        )

        self.match_image_label.pack(side="left", padx=12)

        ctk.CTkButton(
            controls,
            text="FIND POSSIBLE MATCHES",
            width=190,
            height=38,
            fg_color=BLUE,
            hover_color="#2563EB",
            command=self.find_image_matches
        ).pack(side="right")

        self.match_results = ctk.CTkScrollableFrame(
            self.main_area,
            fg_color="transparent"
        )

        self.match_results.pack(
            fill="both", expand=True, padx=0, pady=(10, 20)
        )


    # ========================================================
    # SELECT IMAGE FOR MATCHING
    # ========================================================

    def select_match_image(self):

        path = filedialog.askopenfilename(
            title="Select an Item Image",
            filetypes=[
                ("Image Files", "*.png *.jpg *.jpeg *.webp"),
                ("All Files", "*.*")
            ]
        )

        if not path:
            return

        self.match_image_path = path

        self.match_image_label.configure(
            text=os.path.basename(path),
            text_color=CYAN
        )


    # ========================================================
    # FIND POSSIBLE IMAGE MATCHES
    # ========================================================

    def find_image_matches(self):

        for widget in self.match_results.winfo_children():
            widget.destroy()

        if Image is None:
            messagebox.showerror(
                "Pillow Required",
                "Install Pillow using: python -m pip install Pillow"
            )
            return

        if not self.match_image_path:
            messagebox.showwarning(
                "No Image",
                "Please select an image first."
            )
            return

        selected_signature = image_signature(self.match_image_path)

        if selected_signature is None:
            messagebox.showerror(
                "Image Error",
                "The selected image could not be processed."
            )
            return

        selected_type = self.match_type.get()
        opposite_type = "Found" if selected_type == "Lost" else "Lost"

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute(f"""
            SELECT {ITEM_COLUMNS}
            FROM items
            WHERE type = ?
            AND image_path IS NOT NULL
            AND image_path != ''
            AND status != 'Claimed'
            ORDER BY id DESC
        """, (opposite_type,))

        candidates = cursor.fetchall()

        connection.close()

        matches = []

        for item in candidates:

            similarity = image_similarity(
                selected_signature,
                image_signature(item[8])
            )

            if similarity is None:
                continue

            if similarity >= MATCH_THRESHOLD:
                matches.append((similarity, item))

        matches.sort(key=lambda result: result[0], reverse=True)

        if not matches:
            self.show_empty_state(
                self.match_results,
                "No possible matches found",
                "Try another image or check again after more reports are submitted."
            )
            return

        for similarity, item in matches:
            self.create_match_card(self.match_results, similarity, item)


    # ========================================================
    # IMAGE MATCH RESULT CARD
    # ========================================================

    def create_match_card(self, parent, similarity, item):

        (
            item_id,
            owner,
            item_type,
            item_name,
            location,
            date,
            description,
            status,
            image_path
        ) = item

        card = ctk.CTkFrame(
            parent,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        card.pack(fill="x", padx=35, pady=8)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(15, 8))

        ctk.CTkLabel(
            top,
            text="POSSIBLE MATCH",
            text_color=CYAN,
            font=ctk.CTkFont(size=10, weight="bold")
        ).pack(side="left")

        ctk.CTkLabel(
            top,
            text=f"{similarity}% SIMILARITY",
            text_color=GREEN if similarity >= 75 else CYAN,
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="right")

        ctk.CTkLabel(
            card,
            text=item_name,
            text_color=WHITE,
            font=ctk.CTkFont(size=17, weight="bold")
        ).pack(anchor="w", padx=18, pady=(0, 5))

        ctk.CTkLabel(
            card,
            text=f"{item_type} item  •  {location}  •  {date}",
            text_color=MUTED,
            font=ctk.CTkFont(size=10)
        ).pack(anchor="w", padx=18, pady=(0, 8))

        ctk.CTkLabel(
            card,
            text=description,
            text_color=TEXT,
            font=ctk.CTkFont(size=11),
            wraplength=750,
            justify="left"
        ).pack(anchor="w", padx=18, pady=(0, 10))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(anchor="e", padx=15, pady=(0, 12))

        ctk.CTkButton(
            actions,
            text="VIEW REPORT",
            width=120,
            height=32,
            fg_color=BLUE,
            hover_color="#2563EB",
            command=lambda i=item_id: self.view_match_details(i)
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            actions,
            text="NOTIFICATION PREVIEW",
            width=175,
            height=32,
            fg_color=PURPLE,
            hover_color="#7C3AED",
            command=lambda i=item_id: self.show_notification_preview(i)
        ).pack(side="left", padx=5)


    # ========================================================
    # VIEW MATCH DETAILS
    # ========================================================

    def view_match_details(self, item_id):

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute(f"""
            SELECT {ITEM_COLUMNS}
            FROM items
            WHERE id = ?
        """, (item_id,))

        item = cursor.fetchone()

        connection.close()

        if not item:
            messagebox.showerror(
                "Report Not Found",
                "This report may have been deleted."
            )
            return

        window = ctk.CTkToplevel(self)
        window.title("Possible Match Details")
        window.geometry("550x570")
        window.configure(fg_color=BG)
        window.after(100, window.grab_set)

        card = ctk.CTkFrame(window, fg_color=CARD, corner_radius=15)
        card.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            card,
            text="POSSIBLE MATCH DETAILS",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=CYAN
        ).pack(anchor="w", padx=20, pady=(20, 15))

        details = [
            ("ITEM", item[3]),
            ("TYPE", item[2]),
            ("LOCATION", item[4]),
            ("DATE", item[5]),
            ("STATUS", item[7]),
            ("DESCRIPTION", item[6]),
            ("REPORTED BY", item[1])
        ]

        for label, value in details:

            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=MUTED
            ).pack(anchor="w", padx=20, pady=(7, 2))

            ctk.CTkLabel(
                card,
                text=str(value),
                font=ctk.CTkFont(size=12),
                text_color=WHITE,
                wraplength=450,
                justify="left"
            ).pack(anchor="w", padx=20)


    # ========================================================
    # RUN A TASK IN THE BACKGROUND (keeps the window responsive)
    # ========================================================

    def run_in_background(self, task, on_done):

        result = {}

        def worker():
            try:
                task()
                result["error"] = None
            except Exception as error:
                result["error"] = error

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if "error" in result:
                on_done(result["error"])
            else:
                self.after(150, poll)

        self.after(150, poll)


    # ========================================================
    # EMAIL AND SMS NOTIFICATIONS
    # ========================================================

    def show_notification_preview(self, item_id):

        connection = connect_database()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT student_number, type, item, location, date
            FROM items
            WHERE id = ?
        """, (item_id,))

        item = cursor.fetchone()

        if not item:
            connection.close()
            messagebox.showerror(
                "Not Found",
                "The report could not be found."
            )
            return

        owner_number, item_type, item_name, location, date = item

        cursor.execute("""
            SELECT name, email, phone
            FROM users
            WHERE student_number = ?
        """, (owner_number,))

        owner = cursor.fetchone()

        connection.close()

        owner_name = owner[0] if owner else "Student"
        owner_email = (owner[1] if owner else None) or ""
        owner_phone = (owner[2] if owner else None) or ""

        window = ctk.CTkToplevel(self)
        window.title("Send Notification")
        window.geometry("650x820")
        window.configure(fg_color=BG)
        window.after(100, window.grab_set)

        ctk.CTkLabel(
            window,
            text="SEND NOTIFICATION",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=CYAN
        ).pack(anchor="w", padx=25, pady=(25, 5))

        ctk.CTkLabel(
            window,
            text=f"Notify {owner_name} (student {owner_number}) about this possible match.",
            font=ctk.CTkFont(size=11),
            text_color=MUTED
        ).pack(anchor="w", padx=25, pady=(0, 15))

        message = (
            f"Hello {owner_name},\n\n"
            f"A possible matching report has been found for your "
            f"{item_type.lower()} item: {item_name}.\n\n"
            f"Reported location: {location}\n"
            f"Report date: {date}\n\n"
            f"Please open FindBack and review the possible match.\n\n"
            f"Thank you,\nFindBack Campus Lost & Found"
        )

        sms_message = (
            f"FindBack: A possible match was found for "
            f"your {item_type.lower()} item '{item_name}'. "
            f"Please check your campus lost and found report."
        )

        # ---------------- EMAIL ----------------

        email_card = ctk.CTkFrame(
            window,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        email_card.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(
            email_card,
            text="✉  EMAIL",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=CYAN
        ).pack(anchor="w", padx=18, pady=(16, 6))

        email_to = ctk.CTkEntry(
            email_card,
            placeholder_text="Recipient email address",
            height=36,
            fg_color="#0D1525",
            border_color=BORDER
        )

        email_to.pack(fill="x", padx=18, pady=(0, 6))

        if owner_email:
            email_to.insert(0, owner_email)

        ctk.CTkLabel(
            email_card,
            text="Subject: Possible Match Found — FindBack",
            text_color=TEXT
        ).pack(anchor="w", padx=18, pady=3)

        email_box = ctk.CTkTextbox(
            email_card,
            height=150,
            fg_color="#0D1525",
            text_color=WHITE,
            border_color=BORDER,
            border_width=1
        )

        email_box.pack(fill="x", padx=18, pady=(6, 10))
        email_box.insert("1.0", message)

        email_status = ctk.CTkLabel(
            email_card,
            text="" if email_is_configured()
            else "Email not configured. " + SETTINGS_STATUS,
            text_color=MUTED if email_is_configured() else RED,
            wraplength=540,
            justify="left"
        )

        email_status.pack(anchor="w", padx=18)

        email_button = ctk.CTkButton(
            email_card,
            text="SEND EMAIL",
            width=150,
            height=36,
            fg_color=BLUE,
            hover_color="#2563EB"
        )

        email_button.pack(anchor="e", padx=18, pady=(6, 16))

        # ---------------- SMS ----------------

        sms_card = ctk.CTkFrame(
            window,
            fg_color=CARD,
            corner_radius=15,
            border_width=1,
            border_color=BORDER
        )

        sms_card.pack(fill="x", padx=25, pady=8)

        ctk.CTkLabel(
            sms_card,
            text="▣  SMS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=GREEN
        ).pack(anchor="w", padx=18, pady=(16, 6))

        sms_to = ctk.CTkEntry(
            sms_card,
            placeholder_text="Recipient mobile number (09XXXXXXXXX)",
            height=36,
            fg_color="#0D1525",
            border_color=BORDER
        )

        sms_to.pack(fill="x", padx=18, pady=(0, 8))

        if owner_phone:
            sms_to.insert(0, owner_phone)

        ctk.CTkLabel(
            sms_card,
            text=sms_message,
            text_color=TEXT,
            wraplength=540,
            justify="left"
        ).pack(anchor="w", padx=18, pady=(0, 8))

        sms_status = ctk.CTkLabel(
            sms_card,
            text="" if sms_is_configured()
            else "SMS not configured. " + SETTINGS_STATUS,
            text_color=MUTED if sms_is_configured() else RED,
            wraplength=540,
            justify="left"
        )

        sms_status.pack(anchor="w", padx=18)

        sms_button = ctk.CTkButton(
            sms_card,
            text="SEND SMS",
            width=150,
            height=36,
            fg_color=GREEN,
            hover_color="#16A34A"
        )

        sms_button.pack(anchor="e", padx=18, pady=(6, 16))

        # ---------------- ACTIONS ----------------

        def finish(button, status_label, error, success_text):
            button.configure(state="normal")
            if error:
                status_label.configure(
                    text=f"Failed: {error}",
                    text_color=RED
                )
            else:
                status_label.configure(
                    text=success_text,
                    text_color=GREEN
                )

        def do_send_email():

            address = email_to.get().strip()
            body = email_box.get("1.0", "end").strip()

            if not is_valid_email(address):
                email_status.configure(
                    text="Enter a valid recipient email address.",
                    text_color=RED
                )
                return

            email_button.configure(state="disabled")
            email_status.configure(text="Sending email...", text_color=MUTED)

            self.run_in_background(
                lambda: send_email(
                    address,
                    "Possible Match Found — FindBack",
                    body
                ),
                lambda error: finish(
                    email_button, email_status, error,
                    f"Email sent to {address}." + (
                        "  (DEMO MODE: simulated, nothing was actually sent)"
                        if demo_mode() else ""
                    )
                )
            )

        def do_send_sms():

            number = normalize_phone(sms_to.get().strip())

            if not number:
                sms_status.configure(
                    text="Enter a valid mobile number, e.g. 09171234567.",
                    text_color=RED
                )
                return

            sms_button.configure(state="disabled")
            sms_status.configure(text="Sending SMS...", text_color=MUTED)

            self.run_in_background(
                lambda: send_sms(number, sms_message),
                lambda error: finish(
                    sms_button, sms_status, error,
                    f"SMS sent to {number}." + (
                        "  (DEMO MODE: simulated, nothing was actually sent)"
                        if demo_mode() else ""
                    )
                )
            )

        email_button.configure(command=do_send_email)
        sms_button.configure(command=do_send_sms)

        ctk.CTkButton(
            window,
            text="CLOSE",
            width=160,
            height=40,
            fg_color="transparent",
            hover_color=CARD_HOVER,
            border_width=1,
            border_color=BORDER,
            command=window.destroy
        ).pack(pady=15)


    # ========================================================
    # LOG OUT
    # ========================================================

    def logout(self):

        confirm = messagebox.askyesno(
            "Log Out",
            "Are you sure you want to log out?"
        )

        if not confirm:
            return

        self.logged_out = True
        self.destroy()


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

if __name__ == "__main__":

    setup_database()

    while True:

        login = LoginWindow()
        login.mainloop()

        # Window closed without logging in -> quit
        if not login.user:
            break

        app = FindBackApp(*login.user)
        app.mainloop()

        # Window closed without pressing LOG OUT -> quit
        if not app.logged_out:
            break
