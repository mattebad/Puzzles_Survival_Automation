FROM python:3.11-slim

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    numpy==2.1.3 \
    opencv-python-headless==4.10.0.84 \
    pytesseract==0.3.13

WORKDIR /workspace
