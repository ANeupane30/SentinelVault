using System;
using System.Collections.Generic;
using System.Text;

namespace SentinelVault.Application.Interfaces
{
    public interface IPythonAiClient
    {
        Task<string> GetAiResponseAsync(string query);
    }
}
