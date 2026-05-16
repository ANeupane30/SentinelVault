using SentinelVault.Application.DTOs;
using SentinelVault.Domain.Entities;
using SentinelVault.Domain.Enums;

namespace SentinelVault.Application.Interfaces
{
    /// <summary>
    /// Service interface for document management operations.
    /// Handles document upload, retrieval, and status updates following clean architecture principles.
    /// </summary>
    public interface IDocumentService
    {
        /// <summary>
        /// Saves a physical file to local storage and creates a document record.
        /// </summary>
        /// <param name="file">File upload DTO containing file stream and metadata</param>
        /// <param name="userId">The user ID uploading the document</param>
        /// <returns>The created document ID</returns>
        /// <exception cref="ArgumentNullException">Thrown when file is null</exception>
        /// <exception cref="ArgumentException">Thrown when file is invalid or empty</exception>
        /// <exception cref="InvalidOperationException">Thrown when file save fails</exception>
        Task<Guid> SaveDocumentAsync(FileUploadDto file, Guid userId);

        /// <summary>
        /// Updates the status of a document.
        /// </summary>
        /// <param name="documentId">The document ID to update</param>
        /// <param name="status">The new document status</param>
        /// <exception cref="KeyNotFoundException">Thrown when document is not found</exception>
        Task UpdateDocumentStatusAsync(Guid documentId, DocumentStatus status);

        /// <summary>
        /// Retrieves a document by its ID.
        /// </summary>
        /// <param name="documentId">The document ID to retrieve</param>
        /// <returns>The document if found; null otherwise</returns>
        Task<Document?> GetDocumentAsync(Guid documentId);

        /// <summary>
        /// Retrieves all documents for a specific user.
        /// </summary>
        /// <param name="userId">The user ID</param>
        /// <returns>Collection of documents belonging to the user</returns>
        Task<IEnumerable<Document>> GetUserDocumentsAsync(Guid userId);
    }
}
