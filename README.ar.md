# وجيز

[English README](README.md)

وجيز هو تطبيق ويب عربي يعتمد على الذكاء الاصطناعي لتصنيف القضايا القانونية وتلخيصها، مع دعم رفع الملفات، واستخدام OCR للملفات الممسوحة ضوئياً، وتصدير النتائج إلى PDF، بالإضافة إلى لوحة متابعة لعرض النتائج السابقة.

## المميزات

- تصنيف القضايا القانونية العربية
- تلخيص النصوص القانونية تلقائياً
- دعم رفع ملفات `PDF` و `DOC` و `DOCX` و `TXT` والصور
- دعم `OCR` للملفات الممسوحة ضوئياً
- تصدير النتائج إلى `PDF`
- لوحة متابعة تعرض الإحصائيات، والملخصات الأخيرة، وأنواع الملفات، والكلمات البارزة

## لقطات من المشروع

### الصفحة الرئيسية

![Homepage](docs/screenshots/homepage.png)

### صفحة التحليل والنتيجة

![Result](docs/screenshots/result.png)

## التقنيات المستخدمة

- Python
- Flask
- Flask-Login
- Flask-SQLAlchemy
- scikit-learn
- Transformers
- PyTorch
- Tesseract OCR
- Chart.js

## التشغيل محلياً

```powershell
cd C:\Users\bushr\OneDrive\Desktop\Project\Project
.\.venv\Scripts\python.exe app.py
```

ثم افتح:

- [http://127.0.0.1:5000/](http://127.0.0.1:5000/)

## تثبيت المتطلبات

```powershell
pip install -r requirements.txt
```

## ملاحظات مهمة

- ملف النموذج الكبير `AraBART_5epoch_5e5/model/model.safetensors` غير موجود حالياً في المستودع على GitHub لتقليل حجم المشروع.
- لتشغيل التلخيص الكامل محلياً، أعد وضع ملف النموذج داخل نفس المسار.
- مجلدات البيئة الافتراضية غير مضافة إلى Git.
- قاعدة البيانات المحلية داخل `instance/` غير مضافة إلى Git.

## بنية المشروع

```text
Project/
├── app.py
├── requirements.txt
├── README.md
├── README.ar.md
├── static/
├── templates/
├── ocr-data/
├── AraBART_5epoch_5e5/
├── svm_model.pkl
└── tfidf_vectorizer.pkl
```
