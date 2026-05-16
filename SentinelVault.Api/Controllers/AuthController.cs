using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SentinelVault.Application.DTOs;
using SentinelVault.Application.Interfaces;
using SentinelVault.Api.Responses;

namespace SentinelVault.Api.Controllers
{
    /// <summary>Authentication controller for user registration and login.</summary>
    [ApiController]
    [Route("api/v1/[controller]")]
    [Produces("application/json")]
    public class AuthController(IAuthenticationService authService, ILogger<AuthController> logger) : ControllerBase
    {
        /// <summary>Registers a new user and returns a JWT token.</summary>
        [HttpPost("register")]
        [AllowAnonymous]
        public async Task<ActionResult<ApiResponse<AuthResponseDto>>> Register([FromBody] RegisterDto registerDto)
        {
            try
            {
                if (registerDto == null)
                    return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Invalid request", "Request body is required"));

                var result = await authService.RegisterAsync(registerDto);
                logger.LogInformation("User {UserId} registered successfully", result.UserId);
                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "User registered successfully", result));
            }
            catch (ArgumentException ex)
            {
                logger.LogWarning("Registration validation error: {Message}", ex.Message);
                return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Validation failed", ex.Message));
            }
            catch (InvalidOperationException ex)
            {
                logger.LogWarning("Registration error: {Message}", ex.Message);
                return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Registration failed", ex.Message));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error during registration");
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred during registration"));
            }
        }

        /// <summary>Authenticates a user and returns a JWT token.</summary>
        [HttpPost("login")]
        [AllowAnonymous]
        public async Task<ActionResult<ApiResponse<AuthResponseDto>>> Login([FromBody] LoginDto loginDto)
        {
            try
            {
                if (loginDto == null)
                    return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Invalid request", "Request body is required"));

                var result = await authService.LoginAsync(loginDto);
                logger.LogInformation("User {UserId} logged in successfully", result.UserId);
                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Login successful", result));
            }
            catch (ArgumentException ex)
            {
                logger.LogWarning("Login validation error: {Message}", ex.Message);
                return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Invalid input", ex.Message));
            }
            catch (UnauthorizedAccessException ex)
            {
                logger.LogWarning("Failed login attempt: {Message}", ex.Message);
                return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Authentication failed", ex.Message));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error during login");
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred during login"));
            }
        }

        /// <summary>Debug endpoint to verify JWT token claims.</summary>
        [HttpGet("claims")]
        [Authorize]
        public ActionResult<ApiResponse<object>> GetTokenClaims()
        {
            var claims = User.Claims.ToDictionary(c => c.Type, c => c.Value);
            logger.LogInformation("Token claims requested. Claims: {@Claims}", claims);
            return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Token claims retrieved", claims));
        }

        /// <summary>Creates a standardized successful API response.</summary>
        private static ApiResponse<T> CreateSuccessResponse<T>(int statusCode, string message, T data)
        {
            return new ApiResponse<T>
            {
                Success = true,
                StatusCode = statusCode,
                Message = message,
                Data = data
            };
        }

        /// <summary>Creates a standardized error API response.</summary>
        private ApiResponse<object> CreateErrorResponse(int statusCode, string code, string description)
        {
            return new ApiResponse<object>
            {
                Success = false,
                StatusCode = statusCode,
                Message = "An error occurred",
                Error = new ErrorDetails
                {
                    Code = code,
                    Description = description,
                    AdditionalInfo = new Dictionary<string, object>
                    {
                        { "traceId", HttpContext.TraceIdentifier }
                    }
                }
            };
        }
    }
}
