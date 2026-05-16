using SentinelVault.Application.Interfaces;
using System.Text.Json;
using Microsoft.Extensions.Caching.Distributed;

namespace SentinelVault.Infrastructure.Services
{
    /// <summary>Distributed cache service using Redis.</summary>
    public class RedisCacheService : ICacheService
    {
        private readonly IDistributedCache _cache;

        public RedisCacheService(IDistributedCache cache) => _cache = cache;

        /// <summary>Gets a cached value by key.</summary>
        public async Task<T?> GetAsync<T>(string key)
        {
            var data = await _cache.GetStringAsync(key);
            return data == null ? default : JsonSerializer.Deserialize<T>(data);
        }

        /// <summary>Sets a cached value with optional expiration.</summary>
        public async Task SetAsync<T>(string key, T value, TimeSpan? expiration = null)
        {
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = expiration ?? TimeSpan.FromHours(1)
            };
            await _cache.SetStringAsync(key, JsonSerializer.Serialize(value), options);
        }

        /// <summary>Removes a cached value by key.</summary>
        public async Task RemoveAsync(string key)
        {
            await _cache.RemoveAsync(key);
        }
    }
}
