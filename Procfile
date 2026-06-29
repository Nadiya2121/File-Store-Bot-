FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Koyeb ওয়েব সার্ভিসের হেলথ চেকের জন্য পোর্ট এক্সপোজ করা হলো
EXPOSE 8000

CMD ["python", "main.py"]
