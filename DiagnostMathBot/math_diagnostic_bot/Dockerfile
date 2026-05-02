FROM python:3.11-slim

WORKDIR /app

COPY DiagnostMathBot/math_diagnostic_bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY DiagnostMathBot/math_diagnostic_bot/ .

RUN mkdir -p /app/data/stubs

ENV DB_PATH=/app/data/bot.db

CMD ["python", "main.py"]
