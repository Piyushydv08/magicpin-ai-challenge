FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Render sets the PORT environment variable)
EXPOSE 8080

# Start FastAPI using uvicorn. 
# We use sh -c so that $PORT is properly expanded.
CMD ["sh", "-c", "uvicorn bot:app --host 0.0.0.0 --port ${PORT:-8080}"]
