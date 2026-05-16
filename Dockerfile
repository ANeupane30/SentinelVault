# Use the .NET 10 SDK to build all projects
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Copy all .csproj files to restore dependencies
COPY ["SentinelVault.Api/SentinelVault.Api.csproj", "SentinelVault.Api/"]
COPY ["SentinelVault.Application/SentinelVault.Application.csproj", "SentinelVault.Application/"]
COPY ["SentinelVault.Domain/SentinelVault.Domain.csproj", "SentinelVault.Domain/"]
COPY ["SentinelVault.Infrastructure/SentinelVault.Infrastructure.csproj", "SentinelVault.Infrastructure/"]

RUN dotnet restore "SentinelVault.Api/SentinelVault.Api.csproj"

# Copy the remaining source code and publish
COPY . .
WORKDIR "/src/SentinelVault.Api"
RUN dotnet publish "SentinelVault.Api.csproj" -c Release -o /app/publish

# Final runtime image
FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "SentinelVault.Api.dll"]