using SentinelVault.Application.DTOs;

namespace SentinelVault.Application.Interfaces
{
    /// <summary>
    /// Service interface for user authentication and JWT token generation
    /// </summary>
    public interface IAuthenticationService
    {
        /// <summary>
        /// Register a new user
        /// </summary>
        Task<AuthResponseDto> RegisterAsync(RegisterDto registerDto);

        /// <summary>
        /// Login user and generate JWT token
        /// </summary>
        Task<AuthResponseDto> LoginAsync(LoginDto loginDto);

        /// <summary>
        /// Generate JWT token for a user
        /// </summary>
        string GenerateToken(Guid userId, string email);

        /// <summary>
        /// Validate email format
        /// </summary>
        bool IsValidEmail(string email);
    }

    /// <summary>
    /// User repository interface
    /// </summary>
    public interface IUserRepository
    {
        /// <summary>
        /// Get user by email
        /// </summary>
        Task<SentinelVault.Domain.Entities.User?> GetByEmailAsync(string email);

        /// <summary>
        /// Get user by ID
        /// </summary>
        Task<SentinelVault.Domain.Entities.User?> GetByIdAsync(Guid id);

        /// <summary>
        /// Create new user
        /// </summary>
        Task<SentinelVault.Domain.Entities.User> CreateAsync(SentinelVault.Domain.Entities.User user);

        /// <summary>
        /// Check if email already exists
        /// </summary>
        Task<bool> EmailExistsAsync(string email);
    }
}
