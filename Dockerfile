# Render用：Places API + ローカルアップロード対応（Playwrightなし）
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir streamlit Pillow

COPY app.py places_api_fetcher.py ./

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
