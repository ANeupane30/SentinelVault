using System;
using SentinelVault.Domain.Enums;

namespace SentinelVault.Domain.Entities
{
    public class Document
    {
        public Guid Id { get; set; } = Guid.NewGuid();
        public string FileName { get; set; } = string.Empty;
        public string FilePath { get; set; } = string.Empty;
        public Guid UserId { get; set; }
        public DateTime CreatedDate { get; set; }
        public DateTime UploadedAt { get; set; }
        public DocumentStatus Status { get; set; } = DocumentStatus.Pending;
    }
}
