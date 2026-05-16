using Microsoft.Extensions.Configuration;
using SentinelVault.Application.DTOs;
using SentinelVault.Application.Interfaces;
using SentinelVault.Domain.Entities;
using SentinelVault.Domain.Enums;

namespace SentinelVault.Infrastructure.Services
{
    /// <summary>Service for handling file uploads and document management.</summary>
    public class DocumentService(IDocumentRepository repository, IConfiguration configuration) : IDocumentService
    {
        private readonly string _uploadPath = configuration["Storage:UploadPath"] ?? Path.Combine(Directory.GetCurrentDirectory(), "LocalVault");
        private const long MaxFileSizeBytes = 52_428_800; // 50 MB
        private static readonly string[] AllowedExtensions = { ".pdf", ".doc", ".docx", ".txt", ".xlsx", ".xls", ".pptx", ".ppt" };

        /// <summary>Saves a file and its metadata.</summary>
        public async Task<Guid> SaveDocumentAsync(FileUploadDto file, Guid userId)
        {
            ValidateFile(file);

            if (!Directory.Exists(_uploadPath))
                Directory.CreateDirectory(_uploadPath);

            var uniqueFileName = $"{Guid.NewGuid()}_{SanitizeFileName(file.FileName)}";
            var filePath = Path.Combine(_uploadPath, uniqueFileName);

            try
            {
                using (var fileStream = new FileStream(filePath, FileMode.Create, FileAccess.Write))
                {
                    await file.FileStream.CopyToAsync(fileStream);
                }
            }
            catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException)
            {
                throw new InvalidOperationException($"Failed to save file to disk: {ex.Message}", ex);
            }

            var document = new Document
            {
                FileName = file.FileName,
                FilePath = filePath,
                UserId = userId,
                Status = DocumentStatus.Uploaded,
                UploadedAt = DateTime.UtcNow
            };

            try
            {
                return await repository.SaveMetadataAsync(document);
            }
            catch
            {
                if (File.Exists(filePath))
                {
                    try { File.Delete(filePath); } catch { /* Ignore cleanup errors */ }
                }
                throw;
            }
        }

        /// <summary>Updates the status of a document.</summary>
        public async Task UpdateDocumentStatusAsync(Guid documentId, DocumentStatus status)
        {
            var document = await repository.GetByIdAsync(documentId) ?? throw new KeyNotFoundException($"Document with ID {documentId} not found.");
            await repository.UpdateStatusAsync(documentId, status);
        }

        /// <summary>Retrieves a document by its ID.</summary>
        public async Task<Document?> GetDocumentAsync(Guid documentId)
        {
            return await repository.GetByIdAsync(documentId);
        }

        /// <summary>Retrieves all documents for a specific user.</summary>
        public async Task<IEnumerable<Document>> GetUserDocumentsAsync(Guid userId)
        {
            return await repository.GetByUserIdAsync(userId);
        }

        /// <summary>Validates the uploaded file.</summary>
        private static void ValidateFile(FileUploadDto file)
        {
            if (file == null) throw new ArgumentNullException(nameof(file), "File cannot be null.");
            if (string.IsNullOrWhiteSpace(file.FileName)) throw new ArgumentException("File name cannot be empty.", nameof(file.FileName));
            if (file.FileStream == null || file.FileStream.Length == 0) throw new ArgumentException("File stream cannot be null or empty.", nameof(file.FileStream));
            if (file.FileSize > MaxFileSizeBytes) throw new ArgumentException($"File size cannot exceed {MaxFileSizeBytes / (1024 * 1024)} MB.", nameof(file.FileSize));
            var fileExtension = Path.GetExtension(file.FileName).ToLowerInvariant();
            if (!AllowedExtensions.Contains(fileExtension)) throw new ArgumentException($"File type '{fileExtension}' is not allowed. Allowed types: {string.Join(", ", AllowedExtensions)}", nameof(file.FileName));
        }

        /// <summary>Sanitizes a file name to prevent security issues.</summary>
        private static string SanitizeFileName(string fileName)
        {
            var sanitized = string.Concat(fileName.Split(Path.GetInvalidFileNameChars()));
            return sanitized.Length > 255 ? sanitized[..255] : sanitized;
        }
    }
}
