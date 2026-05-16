using SentinelVault.Domain.Entities;
using SentinelVault.Domain.Enums;

namespace SentinelVault.Application.Interfaces
{
    /// <summary>
    /// Repository interface for document persistence operations.
    /// </summary>
    public interface IDocumentRepository
    {
        /// <summary>
        /// Saves document metadata to the database.
        /// </summary>
        Task<Guid> SaveMetadataAsync(Document document);

        /// <summary>
        /// Retrieves a document by its ID.
        /// </summary>
        Task<Document?> GetByIdAsync(Guid id);

        /// <summary>
        /// Retrieves all documents for a specific user.
        /// </summary>
        Task<IEnumerable<Document>> GetByUserIdAsync(Guid userId);

        /// <summary>
        /// Updates the status of a document.
        /// </summary>
        Task UpdateStatusAsync(Guid id, DocumentStatus status);
    }
}
