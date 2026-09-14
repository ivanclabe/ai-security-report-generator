FROM python:3.12-slim

WORKDIR /app

# libreoffice-writer (not the full libreoffice meta-package) is enough to convert the
# generated .docx to PDF headlessly -- see app/services/report/document.py. This is the
# single largest layer in this image; if PDF is ever not needed in a given deployment,
# this line is the one to drop.
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY data /data

ENV MOCK_DATA_PATH=/data/mock_security_data.json \
    EXCEL_DATA_PATH=/data/thomas_tgs_tps_alarmas_julio.xlsx \
    MITRE_TACTICS_PATH=/data/mitre_tactics.json

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
