FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including those needed for C++ extensions
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    pkg-config \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Run the bot
CMD ["python", "bot.py"]
