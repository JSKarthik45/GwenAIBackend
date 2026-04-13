FROM python:3.10-slim

# Install Node.js (includes npm/npx) required for Expo template bootstrap
RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates gnupg \
	&& curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
	&& apt-get install -y --no-install-recommends nodejs \
	&& apt-get clean \
	&& rm -rf /var/lib/apt/lists/*

# Create a non-root user (Required by HF)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Install dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies used by upload-to-snack.js
COPY --chown=user package.json package-lock.json* ./
RUN npm install --omit=dev

# Copy the rest of your code
COPY --chown=user . .

# Run FastAPI on the port HF expects (7860)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]