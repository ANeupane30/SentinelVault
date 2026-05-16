using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SentinelVault.Application.Interfaces;
using SentinelVault.Api.Responses;
using System.Security.Claims;

namespace SentinelVault.Api.Controllers
{
    /// <summary>Chat controller for AI query endpoints.</summary>
    [ApiController]
    [Route("api/v1/[controller]")]
    [Authorize]
    [Produces("application/json")]
    public class ChatController : ControllerBase
    {
        private readonly IChatService _chatService;
        private readonly ILogger<ChatController> _logger;

        public ChatController(IChatService chatService, ILogger<ChatController> logger)
        {
            _chatService = chatService;
            _logger = logger;
        }

        /// <summary>Sends a query to the AI service with caching.</summary>
        [HttpPost("query")]
        public async Task<ActionResult<ApiResponse<object>>> Query([FromBody] ChatQueryRequest request)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(request?.Query))
                {
                    return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Invalid request", "Query cannot be empty"));
                }

                var userId = ExtractUserIdFromToken();
                if (userId == Guid.Empty)
                {
                    return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Invalid authentication", "User ID not found in token"));
                }

                var response = await _chatService.GetChatResponseAsync(request.Query);

                _logger.LogInformation("Chat query processed for user {UserId}", userId);

                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Query processed successfully", new
                {
                    answer = response
                }));
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected error processing chat query");
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred"));
            }
        }

        /// <summary>Extracts user ID from JWT token.</summary>
        private Guid ExtractUserIdFromToken()
        {
            var userIdClaim = User.FindFirst(ClaimTypes.NameIdentifier)?.Value ??
                             User.FindFirst("userId")?.Value;
            return Guid.TryParse(userIdClaim, out var userId) ? userId : Guid.Empty;
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

    /// <summary>Request model for chat queries.</summary>
    public class ChatQueryRequest
    {
        public string Query { get; set; }
    }
}
