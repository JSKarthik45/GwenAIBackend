FROM python:3.10-slim

# Create a non-root user (Required by HF)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Install dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY --chown=user . .

# Run FastAPI on the port HF expects (7860)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]