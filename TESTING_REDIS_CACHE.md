# Testing Redis Cache - Complete Guide

## 🚀 Prerequisites

Before testing, make sure you have:

1. **Redis Server Running**
2. **API Running** (dotnet run)
3. **Postman or cURL** for testing
4. **Valid JWT Token**

---

## 📋 Step 1: Start Redis Server

### Option 1: Using Docker (Recommended)
```bash
# Pull Redis image
docker pull redis:latest

# Run Redis container
docker run -d -p 6379:6379 --name redis-cache redis:latest

# Verify Redis is running
docker ps

# Test Redis connection
redis-cli ping
# Should return: PONG
```

### Option 2: Using Windows Subsystem for Linux (WSL)
```bash
# Install Redis
sudo apt-get install redis-server

# Start Redis
sudo service redis-server start

# Test connection
redis-cli ping
```

### Option 3: Using Redis GUI (Redis Desktop Manager)
- Download: https://github.com/lework/RedisDesktopManager
- Connect to: `localhost:6379`

---

## 📋 Step 2: Update appsettings.json

Make sure your connection string is correct:

```json
{
  "ConnectionStrings": {
    "DefaultConnection": "Server=.;Database=SentinelVaultDb;Trusted_Connection=True;TrustServerCertificate=True;",
    "Redis": "localhost:6379"
  },
  "PythonAI": {
    "BaseUrl": "http://localhost:8000",
    "TimeoutSeconds": 30
  }
}
```

---

## 📋 Step 3: Start the API

```bash
cd "C:\Users\Dipesh\Desktop\My Project\SentinelVault.Api"
dotnet run
```

The API will start on: `https://localhost:7017/api/v1`

---

## 🧪 Step 4: Test Redis Cache with API

### Test Sequence:

#### 1. **Register/Login to Get Token**

```bash
curl -X POST http://localhost:7017/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "Test123456"
  }'
```

**Save the token from response:**
```json
{
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }
}
```

---

#### 2. **Submit First Query (Cache MISS)**

```bash
TOKEN="your-token-here"

curl -X POST http://localhost:7017/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "What is machine learning?"
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "statusCode": 200,
  "message": "Query processed successfully",
  "data": {
    "query": "What is machine learning?",
    "answer": "Machine learning is...",
    "isCached": false,
    "timestamp": "2024-01-15T11:00:00Z"
  }
}
```

**What happens:**
- ❌ Cache MISS (first time)
- 📞 Calls Python AI service
- 💾 Stores response in Redis
- ⏱️ TTL: 1 hour

---

#### 3. **Submit Same Query Again (Cache HIT)**

```bash
curl -X POST http://localhost:7017/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "What is machine learning?"
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "statusCode": 200,
  "message": "Response from cache",
  "data": {
    "query": "What is machine learning?",
    "answer": "Machine learning is...",
    "isCached": true,
    "timestamp": "2024-01-15T11:00:00Z"
  }
}
```

**What happens:**
- ✅ Cache HIT (same query)
- ⚡ Returns immediately from Redis
- 📞 NO call to Python service
- 🚀 Much faster response

---

## 🔍 Verify Cache with Redis CLI

### Check if data is in Redis:

```bash
# Open Redis CLI
redis-cli

# List all keys
KEYS *

# Get a specific cached query
GET "query:abc123def456:user-id"

# See remaining TTL
TTL "query:abc123def456:user-id"
# Returns seconds until expiration

# Delete a key manually
DEL "query:abc123def456:user-id"

# Flush all cache (careful!)
FLUSHALL
```

---

## 📊 Testing Checklist

### Cache Hit/Miss Testing
- [ ] First query → `isCached: false` (Cache MISS)
- [ ] Same query → `isCached: true` (Cache HIT)
- [ ] Different query → `isCached: false` (Cache MISS)
- [ ] Check Redis CLI shows keys

### Performance Testing
- [ ] Cache HIT response time < 50ms
- [ ] Cache MISS response time > 1000ms (depends on Python service)
- [ ] No cache usage → All MISS
- [ ] With cache → Mix of HIT/MISS

### TTL Testing
- [ ] Keys expire after 1 hour
- [ ] TTL command shows correct countdown
- [ ] Expired keys are automatically removed

### Edge Cases
- [ ] Empty query → Error 400
- [ ] No token → Error 401
- [ ] Invalid token → Error 401
- [ ] Different users → Separate cache entries

---

## 📈 Expected Test Results

### Scenario 1: Cache Working Correctly
```
Query 1: "What is AI?" 
  → isCached: false (MISS)
  → Response time: 1500ms
  → Stored in Redis

Query 2: "What is AI?" 
  → isCached: true (HIT)
  → Response time: 20ms
  → Retrieved from Redis

Query 3: "What is ML?" 
  → isCached: false (MISS)
  → Response time: 1500ms
  → Stored in Redis

Query 4: "What is AI?" 
  → isCached: true (HIT)
  → Response time: 20ms
  → Retrieved from Redis
```

---

## 🐛 Troubleshooting

### Issue: "Unable to connect to Redis"
```
Error: No connection could be made because the target machine actively refused it
```

**Solutions:**
1. Check Redis is running: `redis-cli ping`
2. Check connection string in appsettings.json: `"localhost:6379"`
3. Check Redis port (default 6379)
4. Restart Redis service

---

### Issue: Cache not working (always `isCached: false`)
```
All queries show isCached: false even with duplicates
```

**Solutions:**
1. Check Redis connection logs
2. Verify `ICacheService` is registered in DependencyInjection.cs
3. Check appsettings.json connection string
4. Run `KEYS *` in Redis CLI to see if keys are being stored

---

### Issue: "Query not found in cache after 1 hour"
```
Expected behavior - TTL expired
```

**Solution:**
- This is correct! Keys automatically expire after 1 hour
- Either set new TTL or query again (cache MISS)

---

## 🧪 Postman Testing Template

### 1. Login Request
```
POST http://localhost:7017/api/v1/auth/login
Headers:
  Content-Type: application/json

Body:
{
  "email": "test@example.com",
  "password": "Test123456"
}
```

### 2. Chat Query - Cache MISS
```
POST http://localhost:7017/api/v1/chat/query
Headers:
  Content-Type: application/json
  Authorization: Bearer {{token}}

Body:
{
  "query": "Explain quantum computing"
}
```

### 3. Chat Query - Cache HIT (Same as above)
```
(Execute step 2 again immediately)
```

### 4. Clear Cache (Optional)
```
DELETE http://localhost:7017/api/v1/chat/cache/{{cacheKey}}
Headers:
  Authorization: Bearer {{token}}
```

---

## 📊 Performance Metrics

### Without Cache
- Response time: ~1500-2000ms
- Database queries per minute: High
- Python service load: High

### With Cache (HIT)
- Response time: ~20-50ms
- Database queries per minute: Low
- Python service load: Low

### Expected Improvement
- **Speed:** 30-100x faster
- **Throughput:** 10x more requests handled
- **Cost:** Reduced API calls to Python service

---

## ✅ Successful Cache Testing Indicators

1. ✅ Redis server responds to `PING`
2. ✅ Keys appear in Redis CLI: `KEYS *`
3. ✅ First query shows `isCached: false`
4. ✅ Same query shows `isCached: true`
5. ✅ Response times: MISS ~1500ms, HIT ~20ms
6. ✅ Different queries cache separately
7. ✅ Cache expires after TTL

---

## 🚀 Next Steps

After successful cache testing:

1. ✅ Implement Chat Service (if not done)
2. ✅ Test with actual Python AI backend
3. ✅ Monitor cache hit rate
4. ✅ Adjust TTL based on data freshness needs
5. ✅ Add cache invalidation logic
6. ✅ Implement health checks for Redis
7. ✅ Add monitoring/logging for cache usage

---

## 💡 Pro Tips

1. **Monitor Redis Memory:**
   ```bash
   redis-cli INFO memory
   ```

2. **Watch Live Key Changes:**
   ```bash
   redis-cli MONITOR
   ```

3. **Benchmark Performance:**
   ```bash
   redis-cli --latency
   ```

4. **Check Cache Hit Rate:**
   ```bash
   redis-cli INFO stats
   ```

5. **Set Custom TTL:**
   Update this line in ChatService:
   ```csharp
   await _cacheService.SetAsync(cacheKey, response, TimeSpan.FromMinutes(30)); // 30 min instead of 1 hour
   ```

