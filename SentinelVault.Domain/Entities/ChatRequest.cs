using System;
using System.Collections.Generic;
using System.Text;

namespace SentinelVault.Domain.Entities
{
    public class ChatRequest
    {
        public string Query { get; set; } = string.Empty;
    }
    public class ChatResponse
    {
        public string Message { get; set; } = string.Empty;
        public string Source { get; set; } = string.Empty; // Response from "Cache" or "AI"
    }
}
