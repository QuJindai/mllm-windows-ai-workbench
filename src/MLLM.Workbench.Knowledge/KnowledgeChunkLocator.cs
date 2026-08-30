using System.Text;

namespace MLLM.Workbench.Knowledge;

public static class KnowledgeChunkLocator
{
    private const string Marker = ":@";

    public static string CreateChunkId(string documentId, string locator, int ordinal)
    {
        if (string.IsNullOrWhiteSpace(documentId))
            throw new ArgumentException("Document id is required.", nameof(documentId));
        if (string.IsNullOrWhiteSpace(locator))
            throw new ArgumentException("Source locator is required.", nameof(locator));
        if (ordinal < 0)
            throw new ArgumentOutOfRangeException(nameof(ordinal));

        var encoded = Convert.ToBase64String(Encoding.UTF8.GetBytes(locator.Trim()))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');

        return $"{documentId}{Marker}{encoded}:{ordinal:D6}";
    }

    public static bool TryGetLocator(string? chunkId, out string? locator)
    {
        locator = null;
        if (string.IsNullOrWhiteSpace(chunkId)) return false;

        var markerIndex = chunkId.LastIndexOf(Marker, StringComparison.Ordinal);
        if (markerIndex < 0) return false;

        var encodedStart = markerIndex + Marker.Length;
        var ordinalSeparator = chunkId.IndexOf(':', encodedStart);
        if (ordinalSeparator <= encodedStart) return false;

        var encoded = chunkId[encodedStart..ordinalSeparator]
            .Replace('-', '+')
            .Replace('_', '/');
        var remainder = encoded.Length % 4;
        if (remainder != 0) encoded = encoded.PadRight(encoded.Length + (4 - remainder), '=');

        try
        {
            var decoded = Encoding.UTF8.GetString(Convert.FromBase64String(encoded)).Trim();
            if (decoded.Length == 0) return false;
            locator = decoded;
            return true;
        }
        catch (FormatException)
        {
            return false;
        }
    }
}
