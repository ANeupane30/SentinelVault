using System;
using System.Collections.Generic;
using System.Text;

namespace SentinelVault.Application.Interfaces
{
    public interface IChatService
    {
        Task<string> GetChatResponseAsync(string query);
    }
}
