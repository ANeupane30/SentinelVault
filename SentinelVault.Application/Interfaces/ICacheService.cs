using System;

namespace SentinelVault.Application.Interfaces
{
    /// <summary>Interface for distributed cache operations.</summary>
    public interface ICacheService
    {
        /// <summary>Gets a cached value by key.</summary>
        Task<T?> GetAsync<T>(string key);

        /// <summary>Sets a cached value with optional expiration.</summary>
        Task SetAsync<T>(string key, T value, TimeSpan? expiration = null);

        /// <summary>Removes a cached value by key.</summary>
        Task RemoveAsync(string key);
    }
}
