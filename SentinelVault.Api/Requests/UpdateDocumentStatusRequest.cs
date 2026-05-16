namespace SentinelVault.Api.Requests
{
    /// <summary>
    /// Request DTO for updating document status.
    /// </summary>
    public class UpdateDocumentStatusRequest
    {
        /// <summary>
        /// Gets or sets the new document status.
        /// </summary>
        public int Status { get; set; }
    }
}
