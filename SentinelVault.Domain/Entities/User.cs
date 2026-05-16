using System;

namespace SentinelVault.Domain.Entities
{
    /// <summary>
    /// User entity for authentication
    /// </summary>
    public class User
    {
        public Guid Id { get; init; } = Guid.NewGuid();
        public string Email { get; set; } = string.Empty;
        public string PasswordHash { get; set; } = string.Empty;
        public string FirstName { get; set; } = string.Empty;
        public string LastName { get; set; } = string.Empty;
        public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
        public DateTime? LastLogin { get; set; }
        public bool IsActive { get; set; } = true;
    }
}
