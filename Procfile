# পাইথনের স্টেবল লাইটওয়েট ভার্সন ব্যবহার করা হচ্ছে
FROM python:3.11-slim

# প্রোজেক্ট ডিরেক্টরি সেট করা
WORKDIR /app

# প্রয়োজনীয় ডিপেন্ডেন্সি ইনস্টল করা
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# সব ফাইল কপি করা
COPY . .

# রান কমান্ড
CMD ["python", "main.py"]
