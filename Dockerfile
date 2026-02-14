# 1. Use Python 3.10
FROM python:3.10-slim

# 2. Set the folder where code will live inside the server
WORKDIR /app

# 3. Copy your list of libraries (requirements.txt)
COPY requirements.txt .

# 4. Install the libraries
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy all your files (including main.py and the database)
COPY . .

# 6. The start command (No .py here!)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]