FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import gigaam; gigaam._download_model('v3_e2e_ctc', '/models/gigaam'); gigaam._download_tokenizer('v3_e2e_ctc', '/models/gigaam')"
COPY . .
RUN useradd --create-home appuser
USER appuser
ENV OMP_NUM_THREADS=4
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
