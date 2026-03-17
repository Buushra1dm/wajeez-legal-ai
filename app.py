import os
import pickle
import re
import string
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import nltk
import torch
from docx import Document
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from nltk.corpus import stopwords
from pdfplumber import open as open_pdf
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from tashaphyne.stemming import ArabicLightStemmer
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import pyarabic.araby as araby
import arabic_reshaper
import fitz
import pytesseract
from bidi.algorithm import get_display
import pythoncom
from win32com.client import DispatchEx


BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'instance' / 'your_database.db'}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

_CLASSIFIER = None
_VECTORIZER = None
_SUMMARIZER = None
_TOKENIZER = None
_PDF_FONT_REGISTERED = False
_SCHEMA_READY = False

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg"}

TESSERACT_CANDIDATES = [
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
]


def ensure_nltk_resource(resource_path: str, download_name: str) -> None:
    try:
        nltk.data.find(resource_path)
    except LookupError:
        nltk.download(download_name, quiet=True)


ensure_nltk_resource("corpora/stopwords", "stopwords")


def configure_ocr():
    for candidate in TESSERACT_CANDIDATES:
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            break

    local_tessdata = BASE_DIR / "ocr-data"
    if local_tessdata.exists():
        current_prefix = os.environ.get("TESSDATA_PREFIX", "")
        if str(local_tessdata) not in current_prefix:
            os.environ["TESSDATA_PREFIX"] = str(local_tessdata)


def get_ocr_language():
    local_ara = BASE_DIR / "ocr-data" / "ara.traineddata"
    if local_ara.exists():
        return "ara+eng"
    return "eng"


configure_ocr()


@login_manager.user_loader
def load_user(username):
    return db.session.get(Customer, username)


class Customer(UserMixin, db.Model):
    __tablename__ = "customers"

    username = db.Column(db.String(50), primary_key=True, unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    text_entries = db.relationship("TextEntry", backref="customer", lazy=True)

    def __repr__(self):
        return (
            f"<Customer(username='{self.username}', "
            f"full_name='{self.full_name}', email='{self.email}')>"
        )

    def get_id(self):
        return self.username


class TextEntry(db.Model):
    __tablename__ = "text_entries"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), db.ForeignKey("customers.username"), nullable=False)
    full_text = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    file_type = db.Column(db.String(20), nullable=False, default="text")

    def __repr__(self):
        return f"<TextEntry(id='{self.id}', username='{self.username}', category='{self.category}')>"


def load_classifier_assets():
    global _CLASSIFIER, _VECTORIZER
    if _CLASSIFIER is None or _VECTORIZER is None:
        with open(BASE_DIR / "tfidf_vectorizer.pkl", "rb") as file_obj:
            _VECTORIZER = pickle.load(file_obj)
        with open(BASE_DIR / "svm_model.pkl", "rb") as file_obj:
            _CLASSIFIER = pickle.load(file_obj)
    return _VECTORIZER, _CLASSIFIER


def ensure_text_entry_schema():
    inspector = inspect(db.engine)
    column_names = {column["name"] for column in inspector.get_columns("text_entries")}
    if "file_type" not in column_names:
        db.session.execute(
            text("ALTER TABLE text_entries ADD COLUMN file_type VARCHAR(20) NOT NULL DEFAULT 'text'")
        )
        db.session.commit()


@app.before_request
def ensure_database_ready():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    db.create_all()
    ensure_text_entry_schema()
    _SCHEMA_READY = True


def load_summarizer_assets():
    global _SUMMARIZER, _TOKENIZER
    if _SUMMARIZER is None or _TOKENIZER is None:
        model_path = BASE_DIR / "AraBART_5epoch_5e5" / "model"
        tokenizer_path = BASE_DIR / "AraBART_5epoch_5e5" / "tokenizer"
        _SUMMARIZER = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        _TOKENIZER = AutoTokenizer.from_pretrained(tokenizer_path, use_fast=False)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _SUMMARIZER.to(device)
        _SUMMARIZER.eval()
    return _TOKENIZER, _SUMMARIZER


def summarize_text(text, max_input_length=500, max_summary_length=200):
    tokenizer, model = load_summarizer_assets()
    device = next(model.parameters()).device
    inputs = tokenizer.encode(
        text,
        return_tensors="pt",
        max_length=max_input_length,
        truncation=True,
    ).to(device)
    summary_ids = model.generate(
        inputs,
        max_length=max_summary_length,
        num_beams=4,
        early_stopping=True,
    )
    return tokenizer.decode(summary_ids[0], skip_special_tokens=True)


def remove_numbers(text):
    return re.sub(r"\d+", "", text)


def removing_non_arabic(text):
    return re.sub(
        r"[^0-9\u0600-\u06ff\u0750-\u077f\ufb50-\ufbc1\ufbd3-\ufd3f"
        r"\ufd50-\ufd8f\ufe70-\ufefc\uFDF0-\uFDFD.٠-٩]+",
        " ",
        text,
    )


ara_punctuations = """`÷×؛<>_()*&^%][ـ،/:"؟.,'{}~¦+|!"…“–ـ""" + string.punctuation
arabic_stopwords = stopwords.words("arabic")
keyword_stopwords = set(arabic_stopwords) | {
    "هذا",
    "هذه",
    "ذلك",
    "التي",
    "الذي",
    "على",
    "الى",
    "إلى",
    "من",
    "عن",
    "تم",
    "ثم",
    "بعد",
    "قبل",
    "مع",
    "في",
    "هناك",
    "وقد",
    "كما",
    "بأن",
    "لدى",
    "عند",
    "بين",
    "أمام",
    "حول",
    "غير",
    "ضمن",
    "او",
    "أو",
}


def remove_punctuations(text):
    return text.translate(str.maketrans("", "", ara_punctuations))


def remove_tashkeel(text):
    text = text.strip()
    text = re.sub("[إأٱآا]", "ا", text)
    text = re.sub("ى", "ي", text)
    text = re.sub("ؤ", "ء", text)
    text = re.sub("ئ", "ء", text)
    text = re.sub("ة", "ه", text)
    noise = re.compile(
        """
        ّ    |
        َ    |
        ً    |
        ُ    |
        ٌ    |
        ِ    |
        ٍ    |
        ْ    |
        ـ
        """,
        re.VERBOSE,
    )
    text = re.sub(noise, "", text)
    text = re.sub(r"(.)\1+", r"\1\1", text)
    return araby.strip_tashkeel(text)


def remove_stop_words(text):
    words = [word for word in str(text).split() if word not in arabic_stopwords]
    return " ".join(words)


def tokenize_text(text):
    return str(text).split()


def arabic_light_stemmer(text):
    stemmer = ArabicLightStemmer()
    stemmed_tokens = [stemmer.light_stem(token) for token in text]
    return " ".join(stemmed_tokens)


def preprocess_text(text):
    text = remove_numbers(text)
    text = removing_non_arabic(text)
    text = remove_punctuations(text)
    text = remove_stop_words(text)
    text = remove_tashkeel(text)
    text = tokenize_text(text)
    return arabic_light_stemmer(text)


class_mapping = {
    0: "جنائية",
    1: "احوال شخصية",
    2: "عام",
}


def clean_text(text):
    text = str(text).replace("\ufeff", "")
    return re.sub(r"[^\u0600-\u06FF0-9\s]", "", text)


def count_words(text):
    return len([word for word in str(text).split() if word.strip()])


def normalize_file_type(filename):
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        return "pdf"
    if extension in {".doc", ".docx"}:
        return "doc"
    if extension in {".png", ".jpg", ".jpeg"}:
        return "image"
    return "text"


def extract_top_keywords(entries, limit=8):
    counter = Counter()

    for entry in entries:
        cleaned = clean_text(entry.full_text or "")
        tokens = re.findall(r"[\u0600-\u06FF]{3,}", cleaned)
        for token in tokens:
            normalized = remove_tashkeel(token)
            if normalized in keyword_stopwords or len(normalized) < 3:
                continue
            counter[normalized] += 1

    return [{"keyword": keyword, "count": count} for keyword, count in counter.most_common(limit)]


def is_allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS


def decode_text_bytes(file_bytes):
    for encoding in ("utf-8", "utf-8-sig", "cp1256", "cp1252"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def is_legacy_doc_bytes(file_bytes):
    # Legacy .doc files use the Compound File Binary Format magic header.
    return file_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def is_docx_bytes(file_bytes):
    return zipfile.is_zipfile(BytesIO(file_bytes))


def extract_text_from_docx(file_bytes):
    try:
        document = Document(BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "تعذر قراءة ملف Word. يرجى رفع الملف بصيغة DOCX حقيقية وليس DOC أو ملفاً معاد تسميته."
        ) from exc
    return "\n".join(
        paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
    )


def extract_text_from_doc(file_bytes):
    word = None
    document = None
    try:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "source.doc"
            converted_path = temp_path / "converted.docx"
            source_path.write_bytes(file_bytes)

            pythoncom.CoInitialize()
            word = DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(str(source_path))
            # 16 = wdFormatDocumentDefault (.docx)
            document.SaveAs2(str(converted_path), FileFormat=16)
            document.Close(False)
            document = None
            return extract_text_from_docx(converted_path.read_bytes())
    except Exception as exc:
        raise ValueError(
            "تعذر قراءة ملف DOC القديم. حاول فتحه في Word ثم حفظه بصيغة DOCX أو PDF."
        ) from exc
    finally:
        if document is not None:
            document.Close(False)
        if word is not None:
            word.Quit()
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def extract_text_from_pdf(file_bytes):
    extracted_pages = []
    with open_pdf(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = (page.extract_text() or "").strip()
            if page_text:
                extracted_pages.append(page_text)
    return "\n".join(extracted_pages)


def run_ocr_on_image(image_obj):
    try:
        return pytesseract.image_to_string(image_obj, lang=get_ocr_language()).strip()
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "OCR يحتاج إلى تثبيت Tesseract OCR على الجهاز حتى يعمل مع الملفات الممسوحة ضوئياً."
        ) from exc


def extract_text_with_ocr(file_bytes, extension):
    extension = extension.lower()
    if extension == ".pdf":
        text_chunks = []
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
        for page in pdf_document:
            pixmap = page.get_pixmap(dpi=220)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            page_text = run_ocr_on_image(image)
            if page_text:
                text_chunks.append(page_text)
        return "\n".join(text_chunks)

    image = Image.open(BytesIO(file_bytes))
    return run_ocr_on_image(image)


def extract_text_from_upload(file_storage):
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        return "", ""

    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("صيغة الملف غير مدعومة. استخدم PDF أو DOC أو DOCX أو TXT أو صورة.")

    file_bytes = file_storage.read()
    file_storage.stream.seek(0)
    extracted_text = ""

    if extension == ".txt":
        extracted_text = decode_text_bytes(file_bytes)
    elif extension == ".doc":
        extracted_text = extract_text_from_doc(file_bytes)
    elif extension == ".docx":
        if is_docx_bytes(file_bytes):
            extracted_text = extract_text_from_docx(file_bytes)
        elif is_legacy_doc_bytes(file_bytes):
            extracted_text = extract_text_from_doc(file_bytes)
        else:
            raise ValueError(
                "تعذر قراءة ملف Word. يرجى التأكد أن الملف DOCX صحيح أو رفعه بصيغة DOC/PDF."
            )
    elif extension == ".pdf":
        extracted_text = extract_text_from_pdf(file_bytes)
        if not extracted_text.strip():
            extracted_text = extract_text_with_ocr(file_bytes, extension)
    elif extension in {".png", ".jpg", ".jpeg"}:
        extracted_text = extract_text_with_ocr(file_bytes, extension)

    return extracted_text.strip(), filename


def get_pdf_font_name():
    global _PDF_FONT_REGISTERED
    if _PDF_FONT_REGISTERED:
        return "ArabicUI"

    candidate_fonts = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
    ]
    for font_path in candidate_fonts:
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("ArabicUI", str(font_path)))
            _PDF_FONT_REGISTERED = True
            return "ArabicUI"
    raise RuntimeError("لم يتم العثور على خط عربي مناسب لتصدير PDF.")


def prepare_arabic_for_pdf(text):
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)


def build_result_pdf(data):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    font_name = get_pdf_font_name()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArabicTitle",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=20,
        leading=28,
        alignment=2,
        textColor="#7a4330",
    )
    body_style = ParagraphStyle(
        "ArabicBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=12,
        leading=20,
        alignment=2,
        textColor="#2f211b",
    )

    story = [
        Paragraph(prepare_arabic_for_pdf("تقرير وجيز"), title_style),
        Spacer(1, 18),
        Paragraph(
            prepare_arabic_for_pdf(f"تصنيف القضية: {data['classification']}"),
            body_style,
        ),
        Spacer(1, 10),
        Paragraph(prepare_arabic_for_pdf("ملخص القضية:"), body_style),
        Spacer(1, 8),
        Paragraph(prepare_arabic_for_pdf(data["summary"]), body_style),
    ]

    if data.get("source_name"):
        story.extend(
            [
                Spacer(1, 12),
                Paragraph(
                    prepare_arabic_for_pdf(f"مصدر النص: {data['source_name']}"),
                    body_style,
                ),
            ]
        )

    document.build(story)
    buffer.seek(0)
    return buffer


@app.route("/get_category_data")
@login_required
def get_category_data():
    categories = (
        db.session.query(TextEntry.category, db.func.count(TextEntry.category))
        .filter_by(username=current_user.username)
        .group_by(TextEntry.category)
        .all()
    )
    return jsonify(
        {
            "labels": [category[0] for category in categories],
            "data": [category[1] for category in categories],
        }
    )


@app.route("/get_total_documents")
@login_required
def get_total_documents():
    total_documents = TextEntry.query.filter_by(username=current_user.username).count()
    return jsonify({"totalDocuments": total_documents})


@app.route("/get_last_cases")
@login_required
def get_last_cases():
    selected_category = request.args.get("category", "").strip()
    query = TextEntry.query.filter_by(username=current_user.username)
    if selected_category and selected_category != "الكل":
        query = query.filter_by(category=selected_category)

    last_cases = query.order_by(TextEntry.id.desc()).limit(5).all()
    return jsonify(
        {
            "cases": [
                {
                    "type": case.category,
                    "summary": case.summary,
                    "fileType": case.file_type or "text",
                    "summaryWordCount": count_words(case.summary),
                }
                for case in last_cases
            ]
        }
    )


@app.route("/get_dashboard_insights")
@login_required
def get_dashboard_insights():
    entries = (
        TextEntry.query.filter_by(username=current_user.username)
        .order_by(TextEntry.id.desc())
        .all()
    )

    summaries = [entry.summary for entry in entries if entry.summary]
    average_summary_length = 0
    if summaries:
        average_summary_length = round(
            sum(count_words(summary) for summary in summaries) / len(summaries),
            1,
        )

    file_type_counts = Counter((entry.file_type or "text") for entry in entries)
    ordered_file_types = ["text", "pdf", "doc", "image"]
    file_type_breakdown = [
        {"type": file_type, "count": file_type_counts.get(file_type, 0)}
        for file_type in ordered_file_types
    ]

    top_keywords = extract_top_keywords(entries)
    available_case_types = sorted({entry.category for entry in entries if entry.category})

    return jsonify(
        {
            "averageSummaryLength": average_summary_length,
            "fileTypeBreakdown": file_type_breakdown,
            "topKeywords": top_keywords,
            "caseTypeOptions": ["الكل", *available_case_types],
        }
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/result", methods=["GET", "POST"])
@login_required
def result():
    if request.method == "POST":
        input_text = request.form.get("text", "").strip()
        uploaded_file = request.files.get("document")
        source_name = None

        if uploaded_file and uploaded_file.filename:
            try:
                extracted_text, source_name = extract_text_from_upload(uploaded_file)
            except Exception as exc:
                flash(f"تعذر قراءة الملف المرفوع: {exc}", "error")
                return render_template("result.html", input_text=input_text)

            if extracted_text:
                input_text = extracted_text

        if not input_text:
            flash("الرجاء إدخال نص أو رفع ملف قبل الإرسال.", "error")
            return render_template("result.html", input_text=input_text)

        try:
            vectorizer, classifier = load_classifier_assets()
            processed_text = preprocess_text(input_text)
            features = vectorizer.transform([processed_text])
            prediction = classifier.predict(features)
            predicted_class = class_mapping.get(prediction[0], "لم يتم التعرف")
            summarized_text = summarize_text(clean_text(input_text))
        except Exception as exc:
            flash(f"تعذر معالجة النص حالياً: {exc}", "error")
            return render_template("result.html", input_text=input_text)

        text_entry = TextEntry(
            full_text=input_text,
            category=predicted_class,
            summary=summarized_text,
            username=current_user.username,
            file_type=normalize_file_type(source_name or ""),
        )
        db.session.add(text_entry)
        db.session.commit()
        session["latest_result"] = {
            "classification": predicted_class,
            "summary": summarized_text,
            "input_text": input_text,
            "source_name": source_name or "نص مباشر",
        }

        return render_template(
            "result.html",
            classification=predicted_class,
            summary=summarized_text,
            input_text=input_text,
            source_name=source_name,
        )

    return render_template("result.html")


@app.route("/export_result_pdf")
@login_required
def export_result_pdf():
    latest_result = session.get("latest_result")
    if not latest_result:
        flash("لا توجد نتيجة حديثة لتصديرها بعد.", "error")
        return redirect(url_for("result"))

    try:
        pdf_buffer = build_result_pdf(latest_result)
    except Exception as exc:
        flash(f"تعذر إنشاء ملف PDF: {exc}", "error")
        return redirect(url_for("result"))

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name="wajeez-result.pdf",
        mimetype="application/pdf",
    )


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", username=current_user.username)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("profile"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = Customer.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("تم تسجيل الدخول بنجاح!", "success")
            return redirect(url_for("profile"))

        flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/create_account", methods=["GET", "POST"])
def create_account():
    if current_user.is_authenticated:
        return redirect(url_for("profile"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not all([username, full_name, email, password]):
            flash("يرجى تعبئة جميع الحقول.", "error")
            return redirect(url_for("create_account"))

        existing_user = Customer.query.filter(
            (Customer.username == username) | (Customer.email == email)
        ).first()
        if existing_user:
            flash("اسم المستخدم أو البريد الإلكتروني مستخدم بالفعل.", "error")
            return redirect(url_for("create_account"))

        new_customer = Customer(
            username=username,
            full_name=full_name,
            email=email,
            password=generate_password_hash(password),
        )

        db.session.add(new_customer)
        db.session.commit()
        login_user(new_customer)
        flash("تم إنشاء الحساب بنجاح!", "success")
        return redirect(url_for("profile"))

    return render_template("create_account.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج بنجاح!", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_text_entry_schema()
    app.run(debug=True)
