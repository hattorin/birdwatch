FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg libsndfile1 libgomp1 libgl1 libglib2.0-0 && \
    pip install "numpy<2" birdnetlib librosa watchdog tflite-runtime \
    ultralytics opencv-python-headless && \
    apt-get clean

COPY analyze.py /analyze.py
CMD ["python", "-u", "/analyze.py"]
