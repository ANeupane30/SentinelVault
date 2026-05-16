using SentinelVault.Application.Interfaces;
using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace SentinelVault.Infrastructure.Services
{
    /// <summary>Service for handling AI chat queries with Redis caching.</summary>
    public class ChatService : IChatService
    {
        private readonly IPythonAiClient _aiClient;
        private readonly ICacheService _cache;

        public ChatService(IPythonAiClient aiClient, ICacheService cache)
        {
            _aiClient = aiClient;
            _cache = cache;
        }

        /// <summary>Gets a chat response with caching.</summary>
        public async Task<string> GetChatResponseAsync(string query)
        {
            // Generate cache key
            string cacheKey = $"chat_{HashQuery(query)}";

            // Try to get from cache
            var cachedResponse = await _cache.GetAsync<string>(cacheKey);
            if (cachedResponse != null)
            {
                return cachedResponse; // Cache hit
            }

            // Cache miss: Call Python service
            var aiResponse = await _aiClient.GetAiResponseAsync(query);

            // Store in cache
            await _cache.SetAsync(cacheKey, aiResponse, TimeSpan.FromMinutes(30));

            return aiResponse;
        }

        /// <summary>Generates a hash of the query for cache key.</summary>
        private string HashQuery(string query)
        {
            using var sha256 = SHA256.Create();
            var hashBytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(query));
            return Convert.ToBase64String(hashBytes).Substring(0, 16);
        }
    }
}
