# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Restore the exact checkpoint used before the Hugging Face migration.
COPY --chmod=0644 model-cache/v3_e2e_ctc.ckpt model-cache/v3_e2e_ctc_tokenizer.model /models/gigaam/
RUN printf '%s\n' \
    '73e27ec8f904e486ab063d5bb7c6ab701838b7e5a967ee79b71ccc5aefde146f  /models/gigaam/v3_e2e_ctc.ckpt' \
    '0b9a1960898fbfdf5424ab852ea17445eb3da960fba23e977ff100eb0054fbc8  /models/gigaam/v3_e2e_ctc_tokenizer.model' \
    | sha256sum -c -

COPY *.py ./
RUN chmod 0755 /models /models/gigaam && useradd --create-home appuser
USER appuser
ENV OMP_NUM_THREADS=4
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
