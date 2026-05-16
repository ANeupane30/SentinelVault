namespace SentinelVault.Api.Responses
{
    /// <summary>
    /// Base response DTO for all API responses.
    /// </summary>
    public class ApiResponse<T>
    {
        /// <summary>
        /// Gets or sets a value indicating whether the operation was successful.
        /// </summary>
        public bool Success { get; set; }

        /// <summary>
        /// Gets or sets the HTTP status code.
        /// </summary>
        public int StatusCode { get; set; }

        /// <summary>
        /// Gets or sets the response message.
        /// </summary>
        public string Message { get; set; } = string.Empty;

        /// <summary>
        /// Gets or sets the response data.
        /// </summary>
        public T? Data { get; set; }

        /// <summary>
        /// Gets or sets error details if the operation failed.
        /// </summary>
        public ErrorDetails? Error { get; set; }

        /// <summary>
        /// Gets or sets the timestamp when the response was generated.
        /// </summary>
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;
    }

    /// <summary>
    /// Error details DTO.
    /// </summary>
    public class ErrorDetails
    {
        /// <summary>
        /// Gets or sets the error code.
        /// </summary>
        public string Code { get; set; } = string.Empty;

        /// <summary>
        /// Gets or sets the error description.
        /// </summary>
        public string Description { get; set; } = string.Empty;

        /// <summary>
        /// Gets or sets additional error information (trace ID, etc).
        /// </summary>
        public Dictionary<string, object>? AdditionalInfo { get; set; }
    }
}
