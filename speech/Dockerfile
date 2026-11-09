# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Official ai-sage/GigaAM-v3 e2e_ctc release, pinned by revision and file hashes.
ADD --checksum=sha256:3dbcd2ebe1a572cb9a9945eeb3faf8b59180d408e61a61ecda44db30421e7251 --chmod=0644 https://huggingface.co/ai-sage/GigaAM-v3/resolve/cec030b4c4f35d928e4a9044a3bdb29ebd499fac/config.json /models/gigaam/config.json
ADD --checksum=sha256:0b9a1960898fbfdf5424ab852ea17445eb3da960fba23e977ff100eb0054fbc8 --chmod=0644 https://huggingface.co/ai-sage/GigaAM-v3/resolve/cec030b4c4f35d928e4a9044a3bdb29ebd499fac/tokenizer.model /models/gigaam/tokenizer.model
ADD --checksum=sha256:9801f83ef3979779982c4f83ec1c234d7571e8c1a5aa2bfc0b09ceb97a16cd75 --chmod=0644 https://huggingface.co/ai-sage/GigaAM-v3/resolve/cec030b4c4f35d928e4a9044a3bdb29ebd499fac/pytorch_model.bin /models/gigaam/pytorch_model.bin

COPY *.py ./
RUN chmod 0755 /models /models/gigaam && useradd --create-home appuser
USER appuser
ENV OMP_NUM_THREADS=4
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
