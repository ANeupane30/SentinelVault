using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;
using SentinelVault.Application.DTOs;
using SentinelVault.Application.Interfaces;
using SentinelVault.Domain.Entities;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace SentinelVault.Infrastructure.Services
{
    /// <summary>Service for user registration, login, and JWT token generation.</summary>
    public class AuthenticationService(IUserRepository userRepository, IConfiguration configuration, ILogger<AuthenticationService> logger) : IAuthenticationService
    {
        private readonly string _jwtSecret = configuration["Jwt:SecretKey"] ?? throw new InvalidOperationException("JWT secret key is not configured");
        private readonly string _jwtIssuer = configuration["Jwt:Issuer"] ?? "SentinelVault.Api";
        private readonly string _jwtAudience = configuration["Jwt:Audience"] ?? "SentinelVault.Client";
        private readonly int _jwtExpirationMinutes = int.Parse(configuration["Jwt:ExpirationMinutes"] ?? "60");

        /// <summary>Registers a new user.</summary>
        public async Task<AuthResponseDto> RegisterAsync(RegisterDto registerDto)
        {
            ValidateRegistrationInput(registerDto);
            if (await userRepository.EmailExistsAsync(registerDto.Email))
            {
                throw new InvalidOperationException($"User with email '{registerDto.Email}' already exists");
            }

            var user = new User
            {
                Email = registerDto.Email,
                PasswordHash = HashPassword(registerDto.Password),
                FirstName = registerDto.FirstName,
                LastName = registerDto.LastName,
                IsActive = true
            };

            var createdUser = await userRepository.CreateAsync(user);
            logger.LogInformation("User {UserId} registered with email {Email}", createdUser.Id, createdUser.Email);

            var token = GenerateToken(createdUser.Id, createdUser.Email);
            var expiryTime = DateTime.UtcNow.AddMinutes(_jwtExpirationMinutes);

            return new AuthResponseDto
            {
                UserId = createdUser.Id,
                Email = createdUser.Email,
                FirstName = createdUser.FirstName,
                LastName = createdUser.LastName,
                Token = token,
                TokenExpiry = expiryTime
            };
        }

        /// <summary>Logs in a user and generates a JWT token.</summary>
        public async Task<AuthResponseDto> LoginAsync(LoginDto loginDto)
        {
            if (string.IsNullOrWhiteSpace(loginDto.Email) || string.IsNullOrWhiteSpace(loginDto.Password))
            {
                throw new ArgumentException("Email and password are required");
            }

            var user = await userRepository.GetByEmailAsync(loginDto.Email);
            if (user == null || !VerifyPassword(loginDto.Password, user.PasswordHash))
            {
                logger.LogWarning("Failed login attempt for email: {Email}", loginDto.Email);
                throw new UnauthorizedAccessException("Invalid email or password");
            }

            logger.LogInformation("User {UserId} logged in successfully", user.Id);
            var token = GenerateToken(user.Id, user.Email);
            var expiryTime = DateTime.UtcNow.AddMinutes(_jwtExpirationMinutes);

            return new AuthResponseDto
            {
                UserId = user.Id,
                Email = user.Email,
                FirstName = user.FirstName,
                LastName = user.LastName,
                Token = token,
                TokenExpiry = expiryTime
            };
        }

        /// <summary>Generates a JWT token for a given user.</summary>
        public string GenerateToken(Guid userId, string email)
        {
            var tokenHandler = new JwtSecurityTokenHandler();
            var key = Encoding.ASCII.GetBytes(_jwtSecret);
            var tokenDescriptor = new SecurityTokenDescriptor
            {
                Subject = new System.Security.Claims.ClaimsIdentity(new[]
                {
                    new System.Security.Claims.Claim(System.Security.Claims.ClaimTypes.NameIdentifier, userId.ToString()),
                    new System.Security.Claims.Claim(System.Security.Claims.ClaimTypes.Email, email),
                    new System.Security.Claims.Claim("userId", userId.ToString())
                }),
                Expires = DateTime.UtcNow.AddMinutes(_jwtExpirationMinutes),
                Issuer = _jwtIssuer,
                Audience = _jwtAudience,
                SigningCredentials = new SigningCredentials(new SymmetricSecurityKey(key), SecurityAlgorithms.HmacSha256Signature)
            };
            var token = tokenHandler.CreateToken(tokenDescriptor);
            return tokenHandler.WriteToken(token);
        }

        /// <summary>Validates the format of an email address.</summary>
        public bool IsValidEmail(string email)
        {
            if (string.IsNullOrWhiteSpace(email)) return false;
            const string emailPattern = @"^[^@\s]+@[^@\s]+\.[^@\s]+$";
            return Regex.IsMatch(email, emailPattern, RegexOptions.IgnoreCase);
        }

        /// <summary>Hashes a password using PBKDF2 with a random salt.</summary>
        private static string HashPassword(string password)
        {
            byte[] salt = RandomNumberGenerator.GetBytes(16);
            var hash = Rfc2898DeriveBytes.Pbkdf2(password, salt, 10000, HashAlgorithmName.SHA256, 20);
            var hashBytes = new byte[36];
            Buffer.BlockCopy(salt, 0, hashBytes, 0, 16);
            Buffer.BlockCopy(hash, 0, hashBytes, 16, 20);
            return Convert.ToBase64String(hashBytes);
        }

        /// <summary>Verifies a password against its stored hash.</summary>
        private static bool VerifyPassword(string password, string hash)
        {
            try
            {
                var hashBytes = Convert.FromBase64String(hash);
                var salt = new byte[16];
                Buffer.BlockCopy(hashBytes, 0, salt, 0, 16);
                var storedHash = new byte[20];
                Buffer.BlockCopy(hashBytes, 16, storedHash, 0, 20);
                var computedHash = Rfc2898DeriveBytes.Pbkdf2(password, salt, 10000, HashAlgorithmName.SHA256, 20);
                return CryptographicOperations.FixedTimeEquals(storedHash, computedHash);
            }
            catch
            {
                return false;
            }
        }

        /// <summary>Validates user registration input.</summary>
        private void ValidateRegistrationInput(RegisterDto registerDto)
        {
            if (string.IsNullOrWhiteSpace(registerDto.Email) || !IsValidEmail(registerDto.Email))
                throw new ArgumentException("A valid email is required");
            if (string.IsNullOrWhiteSpace(registerDto.Password) || registerDto.Password.Length < 6)
                throw new ArgumentException("Password must be at least 6 characters");
            if (registerDto.Password != registerDto.ConfirmPassword)
                throw new ArgumentException("Passwords do not match");
            if (string.IsNullOrWhiteSpace(registerDto.FirstName))
                throw new ArgumentException("First name is required");
            if (string.IsNullOrWhiteSpace(registerDto.LastName))
                throw new ArgumentException("Last name is required");
        }
    }
}
