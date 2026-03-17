# WAJEEZ

[Arabic README](README.ar.md)

WAJEEZ is an Arabic legal AI web application for classifying legal cases and generating concise summaries. It also supports file uploads, OCR for scanned documents, PDF export, and a user dashboard for reviewing previous analysis results.

## Features

- Arabic legal case classification
- Automatic Arabic text summarization
- Upload support for `PDF`, `DOC`, `DOCX`, `TXT`, and images
- `OCR` support for scanned files
- Export analysis results to `PDF`
- Dashboard with case statistics, recent summaries, file type insights, and keyword highlights

## Screenshots

### Homepage

![Homepage](docs/screenshots/homepage.png)

### Analysis Result

![Result](docs/screenshots/result.png)

## Tech Stack

- Python
- Flask
- Flask-Login
- Flask-SQLAlchemy
- scikit-learn
- Transformers
- PyTorch
- Tesseract OCR
- Chart.js

## Run Locally

```powershell
cd C:\Users\bushr\OneDrive\Desktop\Project\Project
.\.venv\Scripts\python.exe app.py
```

Then open:

- [http://127.0.0.1:5000/](http://127.0.0.1:5000/)

## Install Requirements

```powershell
pip install -r requirements.txt
```

## Notes

- The large model weight file `AraBART_5epoch_5e5/model/model.safetensors` is not included in this GitHub repository to keep the repo lightweight.
- To enable full summarization locally, place the missing model file back into the same path.
- Virtual environment folders are excluded from Git.
- The local database inside `instance/` is excluded from Git.

## Project Structure

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
