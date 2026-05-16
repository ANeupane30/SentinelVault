# Quick Redis Cache Testing - 5 Minutes

## 🚀 Quick Start

### Step 1: Start Redis (Docker)
```bash
docker run -d -p 6379:6379 --name redis redis:latest
docker ps  # Verify running
```

### Step 2: Start API
```bash
cd C:\Users\Dipesh\Desktop\My Project\SentinelVault.Api
dotnet run
# API will be at http://localhost:7017
```

### Step 3: Login to Get Token
```bash
curl -X POST http://localhost:7017/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test123456"}'
```

Copy the `token` value from response.

### Step 4: Test Cache with Chat Query

**First Query (Cache MISS):**
```bash
TOKEN="your-token-here"

curl -X POST http://localhost:7017/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"What is machine learning?"}'
```

Look for: `"isCached": false`

**Second Query (Cache HIT) - Run immediately:**
```bash
curl -X POST http://localhost:7017/api/v1/chat/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query":"What is machine learning?"}'
```

Look for: `"isCached": true` ← **This proves cache is working!**

---

## 📊 What You Should See

### First Request
```json
{
  "data": {
    "query": "What is machine learning?",
    "answer": "Machine learning is...",
    "isCached": false,
    "timestamp": "2024-01-15T11:00:00Z"
  }
}
```
Response time: ~1000-2000ms

### Second Request (Same Query)
```json
{
  "data": {
    "query": "What is machine learning?",
    "answer": "Machine learning is...",
    "isCached": true,
    "timestamp": "2024-01-15T11:00:00Z"
  }
}
```
Response time: ~50ms ← **Much faster!**

---

## 🔍 Verify Cache in Redis

```bash
# Open Redis CLI
redis-cli

# List all cached keys
KEYS *

# See how many seconds until expiration
TTL "query:xyz123:user-id"

# Exit
exit
```

---

## ✅ Success Indicators

1. ✅ First query has `"isCached": false`
2. ✅ Second query has `"isCached": true`
3. ✅ Response time is much faster for cached query
4. ✅ `redis-cli KEYS *` shows your cached data

---

## 🚀 Performance Improvement

| Metric | Without Cache | With Cache |
|--------|--------------|-----------|
| Response Time | 1500ms | 20ms |
| Speedup | Baseline | 75x faster |
| API Calls | Every request | Once per hour |
| Cost | High | Low |

---

## 🧪 Test Different Scenarios

### Test 1: Multiple Different Queries
```bash
# Query A (MISS)
curl ... -d '{"query":"What is AI?"}'

# Query B (MISS)  
curl ... -d '{"query":"What is ML?"}'

# Query A again (HIT)
curl ... -d '{"query":"What is AI?"}'
```

Expected: Mix of cached and non-cached responses

### Test 2: Cache Expiration
```bash
# Query at time T1 (MISS)
# Wait 1 hour
# Query at time T2 (MISS again - cache expired)
```

Expected: Cache expires after 1 hour

---

## 📝 For Postman Users

**Environment Variable Setup:**
```json
{
  "token": "your-token-here",
  "base_url": "http://localhost:7017/api/v1"
}
```

**Request 1: Login**
```
POST {{base_url}}/auth/login
Body: {"email":"test@example.com","password":"Test123456"}
```

**Request 2: Query (MISS)**
```
POST {{base_url}}/chat/query
Auth: Bearer {{token}}
Body: {"query":"What is machine learning?"}
```

**Request 3: Query (HIT)**
```
(Same as Request 2)
```

---

## 🐛 If Cache Isn't Working

### Check 1: Is Redis running?
```bash
redis-cli ping
# Should return: PONG
```

### Check 2: Is connection string correct?
In `appsettings.json`:
```json
"ConnectionStrings": {
  "Redis": "localhost:6379"
}
```

### Check 3: Check API logs
Look for:
- `Cache HIT for query:`
- `Cache MISS for query:`

### Check 4: Verify Redis has data
```bash
redis-cli
KEYS *
# Should show keys like: query:abc123:user-id
```

---

## 🎯 Next Steps After Testing

1. ✅ Cache working? Great!
2. ⏭️ Connect actual Python AI service
3. ⏭️ Test with real documents
4. ⏭️ Monitor cache performance
5. ⏭️ Adjust TTL if needed (currently 1 hour)

