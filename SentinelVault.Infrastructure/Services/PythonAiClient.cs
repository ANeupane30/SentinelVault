using Microsoft.Extensions.Logging;
using SentinelVault.Application.Interfaces;
using System;
using System.Collections.Generic;
using System.Net.Http.Json;
using System.Text;

namespace SentinelVault.Infrastructure.Services
{
    public class PythonAiClient : IPythonAiClient
    {
        private readonly HttpClient _httpClient;
        private readonly ILogger<PythonAiClient> _logger;
        public PythonAiClient(HttpClient httpClient, ILogger<PythonAiClient> logger)
        {
            _httpClient = httpClient;
            _logger = logger;
        }
        //public async Task<string> GetAiResponseAsync(string query)
        //{
        //    try
        //    {
        //        var response = await _httpClient.PostAsJsonAsync("v1/query", new { query });

        //        response.EnsureSuccessStatusCode();

        //        return await response.Content.ReadAsStringAsync();
        //    }
        //    catch (Exception ex)
        //    {
        //        _logger.LogError(ex, "Failed to reach the Python AI service.");
        //        return "Sorry, I'm having trouble connecting to my brain right now.";
        //    }
        //}
        public async Task<string> GetAiResponseAsync(string query)
        {
            await Task.Delay(500); // Simulate network lag
            return $"Mock Response for: {query}";
        }
    }
}
