using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SentinelVault.Application.DTOs;
using SentinelVault.Application.Interfaces;
using SentinelVault.Api.Requests;
using SentinelVault.Api.Responses;
using SentinelVault.Domain.Enums;
using System.Security.Claims;

namespace SentinelVault.Api.Controllers
{
    /// <summary>API controller for document management operations.</summary>
    [ApiController]
    [Route("api/v1/[controller]")]
    [Authorize]
    [Produces("application/json")]
    public class DocumentsController(IDocumentService documentService, ILogger<DocumentsController> logger) : ControllerBase
    {
        /// <summary>Uploads a document file.</summary>
        [HttpPost("upload")]
        [Consumes("multipart/form-data")]
        public async Task<ActionResult<ApiResponse<DocumentUploadResponse>>> Upload(IFormFile file)
        {
            try
            {
                var userId = ExtractUserIdFromToken();
                if (userId == Guid.Empty)
                {
                    logger.LogWarning("Attempted upload without valid user ID in token");
                    return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Invalid authentication", "User ID not found in token"));
                }

                var validationError = ValidateFileUpload(file);
                if (validationError != null)
                {
                    logger.LogWarning("File upload validation failed: {ValidationError}", validationError);
                    return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Validation failed", validationError));
                }

                var fileName = file.FileName;
                var fileSize = file.Length;
                var uploadedAt = DateTime.UtcNow;

                var fileDto = await ConvertFormFileToDto(file);
                var documentId = await documentService.SaveDocumentAsync(fileDto, userId);

                var response = new DocumentUploadResponse
                {
                    DocumentId = documentId,
                    FileName = fileName,
                    FileSize = fileSize,
                    UploadedAt = uploadedAt,
                    Status = DocumentStatus.Uploaded.ToString()
                };

                logger.LogInformation("Document {DocumentId} uploaded successfully by user {UserId}", documentId, userId);
                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "File uploaded successfully", response));
            }
            catch (ArgumentException ex)
            {
                logger.LogWarning("Argument validation error during upload: {Message}", ex.Message);
                return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Validation error", ex.Message));
            }
            catch (InvalidOperationException ex)
            {
                logger.LogError("File system error during upload: {Message}", ex.Message);
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "File storage error", "Failed to save file to storage"));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error during document upload");
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred during file upload"));
            }
        }

        /// <summary>Retrieves a specific document's metadata.</summary>
        [HttpGet("{id:guid}")]
        public async Task<ActionResult<ApiResponse<DocumentResponse>>> GetDocument(Guid id)
        {
            try
            {
                var userId = ExtractUserIdFromToken();
                if (userId == Guid.Empty)
                {
                    logger.LogWarning("Attempted to retrieve document without valid user ID");
                    return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Invalid authentication", "User ID not found in token"));
                }

                var document = await documentService.GetDocumentAsync(id);
                if (document == null)
                {
                    logger.LogWarning("Document {DocumentId} not found", id);
                    return NotFound(CreateErrorResponse(StatusCodes.Status404NotFound, "Document not found", $"Document with ID {id} does not exist"));
                }

                if (document.UserId != userId)
                {
                    logger.LogWarning("User {UserId} attempted to access document {DocumentId} owned by {OwnerId}", userId, id, document.UserId);
                    return Forbid();
                }

                var response = new DocumentResponse
                {
                    Id = document.Id,
                    FileName = document.FileName,
                    FilePath = document.FilePath,
                    UserId = document.UserId,
                    CreatedDate = document.CreatedDate,
                    UploadedAt = document.UploadedAt,
                    Status = document.Status.ToString()
                };

                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Document retrieved successfully", response));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error while retrieving document {DocumentId}", id);
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred while retrieving the document"));
            }
        }

        /// <summary>Retrieves all documents for the authenticated user.</summary>
        [HttpGet]
        public async Task<ActionResult<ApiResponse<IEnumerable<DocumentResponse>>>> GetUserDocuments()
        {
            try
            {
                var userId = ExtractUserIdFromToken();
                if (userId == Guid.Empty)
                {
                    logger.LogWarning("Attempted to retrieve user documents without valid user ID");
                    return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Invalid authentication", "User ID not found in token"));
                }

                var documents = await documentService.GetUserDocumentsAsync(userId);
                var response = documents.Select(doc => new DocumentResponse
                {
                    Id = doc.Id,
                    FileName = doc.FileName,
                    FilePath = doc.FilePath,
                    UserId = doc.UserId,
                    CreatedDate = doc.CreatedDate,
                    UploadedAt = doc.UploadedAt,
                    Status = doc.Status.ToString()
                }).ToList();

                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Documents retrieved successfully", response));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error while retrieving user documents");
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred while retrieving documents"));
            }
        }

        /// <summary>Updates a document's processing status.</summary>
        [HttpPut("{id:guid}/status")]
        public async Task<ActionResult<ApiResponse<object>>> UpdateDocumentStatus(Guid id, [FromBody] UpdateDocumentStatusRequest request)
        {
            try
            {
                if (request == null || !Enum.IsDefined(typeof(DocumentStatus), request.Status))
                {
                    logger.LogWarning("Invalid status value: {StatusValue}", request?.Status);
                    return BadRequest(CreateErrorResponse(StatusCodes.Status400BadRequest, "Invalid status", "The provided status value is invalid"));
                }

                var userId = ExtractUserIdFromToken();
                if (userId == Guid.Empty)
                {
                    logger.LogWarning("Attempted to update document status without valid user ID");
                    return Unauthorized(CreateErrorResponse(StatusCodes.Status401Unauthorized, "Invalid authentication", "User ID not found in token"));
                }

                var document = await documentService.GetDocumentAsync(id);
                if (document == null)
                {
                    logger.LogWarning("Document {DocumentId} not found for status update", id);
                    return NotFound(CreateErrorResponse(StatusCodes.Status404NotFound, "Document not found", $"Document with ID {id} does not exist"));
                }

                if (document.UserId != userId)
                {
                    logger.LogWarning("User {UserId} attempted to update status of document {DocumentId} owned by {OwnerId}", userId, id, document.UserId);
                    return Forbid();
                }

                var newStatus = (DocumentStatus)request.Status;
                await documentService.UpdateDocumentStatusAsync(id, newStatus);

                logger.LogInformation("Document {DocumentId} status updated to {Status} by user {UserId}", id, newStatus, userId);
                return Ok(CreateSuccessResponse(StatusCodes.Status200OK, "Document status updated successfully", new { documentId = id, status = newStatus.ToString() }));
            }
            catch (KeyNotFoundException ex)
            {
                logger.LogWarning("Document not found during status update: {Message}", ex.Message);
                return NotFound(CreateErrorResponse(StatusCodes.Status404NotFound, "Document not found", ex.Message));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Unexpected error while updating document {DocumentId} status", id);
                return StatusCode(StatusCodes.Status500InternalServerError, CreateErrorResponse(StatusCodes.Status500InternalServerError, "Internal server error", "An unexpected error occurred while updating document status"));
            }
        }

        /// <summary>Extracts the user ID from the JWT token claims.</summary>
        private Guid ExtractUserIdFromToken()
        {
            var userIdClaim = User.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value ??
                             User.FindFirst("sub")?.Value ??
                             User.FindFirst("userId")?.Value ??
                             User.FindFirst(System.Security.Claims.ClaimTypes.Sid)?.Value;

            logger.LogDebug("Extracted user ID claim: {UserIdClaim}", userIdClaim);

            if (Guid.TryParse(userIdClaim, out var userId))
            {
                logger.LogDebug("Successfully parsed user ID: {UserId}", userId);
                return userId;
            }

            logger.LogWarning("Failed to extract valid user ID from token. Claim value: {UserIdClaim}", userIdClaim);
            return Guid.Empty;
        }

        /// <summary>Validates the uploaded file against size, type, and content restrictions.</summary>
        private string? ValidateFileUpload(IFormFile file)
        {
            const long maxFileSize = 52_428_800; // 50 MB
            var allowedExtensions = new[] { ".pdf", ".doc", ".docx", ".txt", ".xlsx", ".xls", ".pptx", ".ppt" };

            if (file == null || file.Length == 0)
                return "No file was uploaded.";

            if (file.Length > maxFileSize)
                return $"File size cannot exceed {maxFileSize / (1024 * 1024)} MB.";

            var fileExtension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (!allowedExtensions.Contains(fileExtension))
                return $"File type '{fileExtension}' is not allowed. Allowed types: {string.Join(", ", allowedExtensions)}";

            if (string.IsNullOrWhiteSpace(file.FileName))
                return "File name is required.";

            return null;
        }

        /// <summary>Converts IFormFile to a FileUploadDto for the service layer.</summary>
        private static async Task<FileUploadDto> ConvertFormFileToDto(IFormFile file)
        {
            var stream = new MemoryStream();
            await file.CopyToAsync(stream);
            stream.Position = 0;

            return new FileUploadDto
            {
                FileName = file.FileName,
                FileSize = file.Length,
                FileStream = stream,
                ContentType = file.ContentType ?? "application/octet-stream"
            };
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
