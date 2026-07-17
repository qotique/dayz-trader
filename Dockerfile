FROM python:3.13-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "web.app:get_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
