namespace SentinelVault.Application.DTOs
{
    /// <summary>
    /// DTO for file upload operations - maintains clean architecture by not exposing ASP.NET types
    /// </summary>
    public class FileUploadDto
    {
        public string FileName { get; set; } = string.Empty;
        public long FileSize { get; set; }
        public Stream FileStream { get; set; } = null!;
        public string ContentType { get; set; } = string.Empty;
    }
}
