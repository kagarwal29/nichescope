FROM python:3.10-slim

WORKDIR /app

# Update certificates and install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential gcc g++ gfortran libopenblas-dev liblapack-dev \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml setup.py* setup.cfg* ./
COPY . .

# Install Python dependencies with trusted hosts to bypass SSL issues
RUN pip install --no-cache-dir --trusted-host pypi.python.org --trusted-host files.pythonhosted.org --trusted-host pypi.org --upgrade pip setuptools wheel

RUN pip install --no-cache-dir --trusted-host pypi.python.org --trusted-host files.pythonhosted.org --trusted-host pypi.org -e .

CMD ["uvicorn", "nichescope.main:app", "--host", "0.0.0.0", "--port", "8000"]
