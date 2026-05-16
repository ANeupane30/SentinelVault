using Dapper;
using SentinelVault.Application.Interfaces;
using SentinelVault.Domain.Entities;
using SentinelVault.Infrastructure.Persistence;

namespace SentinelVault.Infrastructure.Repositories
{
    /// <summary>Repository for user data access operations.</summary>
    public class UserRepository(DbConnectionFactory connectionFactory) : IUserRepository
    {
        /// <summary>Gets a user by their email address.</summary>
        public async Task<User?> GetByEmailAsync(string email)
        {
            using var connection = connectionFactory.CreateConnection();
            const string sql = "SELECT Id, Email, PasswordHash, FirstName, LastName, CreatedAt, LastLogin, IsActive FROM Users WHERE Email = @Email AND IsActive = 1";
            return await connection.QueryFirstOrDefaultAsync<User>(sql, new { Email = email });
        }

        /// <summary>Gets a user by their unique identifier.</summary>
        public async Task<User?> GetByIdAsync(Guid id)
        {
            using var connection = connectionFactory.CreateConnection();
            const string sql = "SELECT Id, Email, PasswordHash, FirstName, LastName, CreatedAt, LastLogin, IsActive FROM Users WHERE Id = @Id AND IsActive = 1";
            return await connection.QueryFirstOrDefaultAsync<User>(sql, new { Id = id });
        }

        /// <summary>Creates a new user in the database.</summary>
        public async Task<User> CreateAsync(User user)
        {
            using var connection = connectionFactory.CreateConnection();
            const string sql = "INSERT INTO Users (Id, Email, PasswordHash, FirstName, LastName, CreatedAt, IsActive) VALUES (@Id, @Email, @PasswordHash, @FirstName, @LastName, @CreatedAt, @IsActive)";
            await connection.ExecuteAsync(sql, user);
            return user;
        }

        /// <summary>Checks if an email address already exists in the database.</summary>
        public async Task<bool> EmailExistsAsync(string email)
        {
            using var connection = connectionFactory.CreateConnection();
            const string sql = "SELECT COUNT(1) FROM Users WHERE Email = @Email";
            return await connection.ExecuteScalarAsync<int>(sql, new { Email = email }) > 0;
        }
    }
}
