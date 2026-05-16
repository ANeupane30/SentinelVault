using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("v1/query")] // Match the route in your PythonAiClient
public class MockPythonController : ControllerBase
{
    [HttpPost]
    public IActionResult MockQuery([FromBody] object request)
    {
        // Return a fake AI response
        return Ok("This is a mock response because the Python FastAPI is not ready yet.");
    }
}