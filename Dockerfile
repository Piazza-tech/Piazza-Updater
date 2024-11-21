FROM python:3.11

# Set working directory
WORKDIR /app

# Copy application code
COPY . /app

# Set environment variable
ENV PYTHONPATH="/app"

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port
# EXPOSE 8000

# Start both verba and main.py
CMD ["sh", "-c", "verba start --port 8000 --host 0.0.0.0 & python main.py"]
