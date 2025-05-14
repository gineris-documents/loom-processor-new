FROM python:3.10-slim

WORKDIR /app

# Install FFmpeg and other dependencies
RUN apt-get update && \
    apt-get install -y ffmpeg curl wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install yt-dlp
RUN wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create temp directory
RUN mkdir -p /tmp/loom_videos && \
    chmod 777 /tmp/loom_videos

# Copy application code
COPY app.py .

# Set environment variables
ENV PORT=8080
ENV TEMP_DIR=/tmp/loom_videos

# Expose the port
EXPOSE 8080

# Run the application
CMD exec gunicorn --bind :$PORT app:app
