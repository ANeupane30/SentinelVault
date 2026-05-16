using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Http;
using SentinelVault.Application.Interfaces;
using SentinelVault.Infrastructure.Persistence;
using SentinelVault.Infrastructure.Repositories;
using SentinelVault.Infrastructure.Services;

namespace SentinelVault.Infrastructure
{
    /// <summary>Dependency injection configuration for infrastructure services.</summary>
    public static class DependencyInjection
    {
        /// <summary>Registers infrastructure services with the dependency injection container.</summary>
        public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
        {
            services.AddSingleton<DbConnectionFactory>();

            // Document services
            services.AddScoped<IDocumentRepository, DocumentReposiotry>();
            services.AddScoped<IDocumentService, DocumentService>();

            // Redis cache
            services.AddStackExchangeRedisCache(options =>
            {
                options.Configuration = configuration.GetConnectionString("Redis") ?? "localhost:6379";
                options.InstanceName = "SentinelVault_";
            });
            services.AddScoped<ICacheService, RedisCacheService>();

            // Python AI Client with HttpClient
            services.AddHttpClient<IPythonAiClient, PythonAiClient>(client =>
            {
                var pythonBaseUrl = configuration["PythonAI:BaseUrl"] ?? "http://localhost:8000";
                client.BaseAddress = new Uri(pythonBaseUrl);
                client.Timeout = TimeSpan.FromSeconds(int.Parse(configuration["PythonAI:TimeoutSeconds"] ?? "30"));
            });

            // Authentication services
            services.AddScoped<IUserRepository, UserRepository>();
            services.AddScoped<IAuthenticationService, AuthenticationService>();
            services.AddScoped<IChatService, ChatService>();

            return services;
        }
    }
}
