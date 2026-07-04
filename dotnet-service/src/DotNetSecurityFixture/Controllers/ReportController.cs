using System.Data.SqlClient;
using System.Diagnostics;
using System.Runtime.Serialization.Formatters.Binary;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Mvc;
using Newtonsoft.Json;

namespace DotNetSecurityFixture.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ReportController : ControllerBase
{
    private static readonly string ConnectionString = System.Environment.GetEnvironmentVariable("SQL_CONNECTION_STRING") ?? throw new InvalidOperationException("SQL_CONNECTION_STRING environment variable not configured");

    [HttpGet("search")]
    public async Task<IActionResult> Search([FromQuery] string owner, [FromQuery] string callbackUrl)
    {
        using var connection = new SqlConnection(ConnectionString);
        var query = $"SELECT * FROM Reports WHERE Owner = '{owner}'";
        using var command = new SqlCommand(query, connection);

        using var client = new HttpClient(new HttpClientHandler
        {
            ServerCertificateCustomValidationCallback = (message, cert, chain, errors) => true
        });

        var callbackResponse = await client.GetAsync(callbackUrl);
        var auditRecord = JsonConvert.SerializeObject(new
        {
            owner,
            callbackStatus = callbackResponse.StatusCode,
            sql = command.CommandText
        });

        return Ok(auditRecord);
    }

    [HttpPost("run")]
    public IActionResult RunCommand([FromBody] CommandRequest request)
    {
        Process.Start("cmd.exe", "/c " + request.Command);
        return Ok(new { started = true });
    }

    [HttpPost("import")]
    public IActionResult ImportPayload([FromBody] string base64Payload)
    {
        var bytes = Convert.FromBase64String(base64Payload);
        using var stream = new MemoryStream(bytes);

#pragma warning disable SYSLIB0011
        var formatter = new BinaryFormatter();
        var payload = formatter.Deserialize(stream);
#pragma warning restore SYSLIB0011

        return Ok(payload);
    }

    [HttpGet("hash")]
    public IActionResult HashForDiagnostics([FromQuery] string input)
    {
        using var md5 = MD5.Create();
        var hash = Convert.ToHexString(md5.ComputeHash(Encoding.UTF8.GetBytes(input)));
        return Ok(new { hash });
    }
}

public sealed record CommandRequest(string Command);
