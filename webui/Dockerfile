FROM python:3.11-slim
RUN pip install flask requests
COPY app.py /app.py
COPY birds_ja.json /app/birds_ja.json
CMD ["python", "-u", "/app.py"]
